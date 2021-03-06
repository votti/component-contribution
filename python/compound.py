import openbabel, urllib, re, string, json, logging
from chemaxon import GetDissociationConstants, ChemAxonError
import numpy as np
from thermodynamic_constants import R, debye_huckel
from scipy.misc import logsumexp

MIN_PH = 0.0
MAX_PH = 14.0

class Compound(object):
    
    _obElements = openbabel.OBElementTable()

    def __init__(self, database, compound_id, inchi, pKas, majorMSpH7, nHs, zs):
        self.database = database
        self.compound_id = compound_id
        self.inchi = inchi
        self.pKas = pKas
        self.majorMSpH7 = majorMSpH7
        self.nHs = nHs
        self.zs = zs
    
    @staticmethod
    def from_kegg(cid):
        inchi = Compound.get_inchi(cid)
        if inchi is None:
            pKas = []
            majorMSpH7 = -1
            nHs = []
            zs = []
        else:
            pKas, majorMSpH7, nHs, zs = Compound.get_species_pka(inchi)
        return Compound('KEGG', 'C%05d' % cid, inchi,
                        pKas, majorMSpH7, nHs, zs)

    def to_json_dict(self):
        return {'database' : self.database,
                'id' : self.compound_id,
                'inchi' : self.inchi,
                'pKas' : self.pKas,
                'majorMSpH7' : self.majorMSpH7,
                'nHs' : self.nHs,
                'zs' : self.zs}
    
    @staticmethod
    def from_json_dict(d):
        return Compound(d['database'], d['id'], d['inchi'],
                        d['pKas'], d['majorMSpH7'], d['nHs'], d['zs'])

    @staticmethod
    def get_inchi(cid):
        s_mol = urllib.urlopen('http://rest.kegg.jp/get/cpd:C%05d/mol' % cid).read()
        return Compound.mol2inchi(s_mol)

    @staticmethod
    def mol2inchi(s):
        openbabel.obErrorLog.SetOutputLevel(-1)

        conv = openbabel.OBConversion()
        conv.SetInAndOutFormats('mol', 'inchi')
        conv.AddOption("F", conv.OUTOPTIONS)
        conv.AddOption("T", conv.OUTOPTIONS)
        conv.AddOption("x", conv.OUTOPTIONS, "noiso")
        conv.AddOption("w", conv.OUTOPTIONS)
        obmol = openbabel.OBMol()
        if not conv.ReadString(obmol, s):
            return None
        inchi = conv.WriteString(obmol, True) # second argument is trimWhitespace
        if inchi == '':
            return None
        else:
            return inchi
        
    @staticmethod
    def smiles2inchi(smiles):
        openbabel.obErrorLog.SetOutputLevel(-1)
        
        conv = openbabel.OBConversion()
        conv.SetInAndOutFormats('smiles', 'inchi')
        conv.AddOption("F", conv.OUTOPTIONS)
        conv.AddOption("T", conv.OUTOPTIONS)
        conv.AddOption("x", conv.OUTOPTIONS, "noiso")
        conv.AddOption("w", conv.OUTOPTIONS)
        obmol = openbabel.OBMol()
        conv.ReadString(obmol, smiles)
        inchi = conv.WriteString(obmol, True) # second argument is trimWhitespace
        if inchi == '':
            return None
        else:
            return inchi

    @staticmethod
    def get_atom_bag_and_charge_from_inchi(inchi):
        if inchi is None:
            return {}, 0
        
        fixed_charge = 0
        for q in re.findall('/q([0-9\+\-\;]+)', inchi):
            for s in q.split(';'): 
                if s:
                    fixed_charge += int(s)

        atom_bag = {}
        # the /f field gives the fixed-H structure
        tokens = re.findall('/f([0-9A-Za-z\.]+/)', inchi)

        # if /f is not given, use the main formula and 
        # adjust the number of protons according to the /p field
        if len(tokens) == 0:
            tokens = re.findall('InChI=1S?/([0-9A-Za-z\.]+)', inchi)
            for p in re.findall('/p([0-9\+\-\;]+)', inchi):
                for s in p.split(';'):
                    if s:
                        atom_bag['H'] = atom_bag.get('H', 0) + int(s)

        if len(tokens) == 1:
            formula = tokens[0]
        elif len(tokens) > 1:
            raise ValueError('Bad InChI: ' + inchi)
        else:
            formula = ''

        for mol_formula_times in formula.split('.'):
            for times, mol_formula in re.findall('^(\d+)?(\w+)', mol_formula_times):
                if not times:
                    times = 1
                else:
                    times = int(times)
                for atom, count in re.findall("([A-Z][a-z]*)([0-9]*)", mol_formula):
                    if count == '':
                        count = 1
                    else:
                        count = int(count)
                    atom_bag[atom] = atom_bag.get(atom, 0) + count * times
        
        return atom_bag, fixed_charge
    
    @staticmethod
    def get_species_pka(inchi):
        if inchi is None:
            return [], -1, [], []

        try:
            pKas, major_ms = GetDissociationConstants(inchi)
            pKas = sorted([pka for pka in pKas if pka > MIN_PH and pka < MAX_PH], reverse=True)
            major_ms_inchi = Compound.smiles2inchi(major_ms)
        except ChemAxonError:
            logging.warning('chemaxon failed to find pKas for this inchi: ' + inchi)
            pKas = []
            major_ms_inchi = inchi

        atom_bag, major_ms_charge = Compound.get_atom_bag_and_charge_from_inchi(major_ms_inchi)
        major_ms_nH = atom_bag.get('H', 0)

        n_species = len(pKas) + 1
        if pKas == []:
            majorMSpH7 = 0
        else:
            majorMSpH7 = len([1 for pka in pKas if pka > 7])
            
        nHs = []
        zs = []

        for i in xrange(n_species):
            zs.append((i - majorMSpH7) + major_ms_charge)
            nHs.append((i - majorMSpH7) + major_ms_nH)
        
        return pKas, majorMSpH7, nHs, zs
    
    def __str__(self):
        return "%s\nInChI: %s\npKas: %s\nmajor MS: nH = %d, charge = %d" % \
            (self.compound_id, self.inchi, ', '.join(['%.2f' % p for p in self.pKas]),
             self.nHs[self.majorMSpH7], self.zs[self.majorMSpH7])
    
    def get_atom_bag_with_electrons(self):
        """
            Calculates the number of electrons in a given molecule
            Returns:
                a dictionary of all element counts and also electron count ('e-')
        """
        if self.inchi is None:
            return None
        atom_bag, charge = Compound.get_atom_bag_and_charge_from_inchi(self.inchi)
        n_protons = sum([count * Compound._obElements.GetAtomicNum(str(elem))
                         for (elem, count) in atom_bag.iteritems()])
        atom_bag['e-'] = n_protons - charge
        return atom_bag
        
    def transform(self, pH, I, T):
        if self.inchi is None:
            return 0
        elif self.pKas == []:
            dG0s = np.zeros((1, 1))
        else:
            dG0s = -np.cumsum([0] + self.pKas) * R * T * np.log(10)
            dG0s = dG0s - dG0s[self.majorMSpH7]
        DH = debye_huckel((I, T))
        
        # dG0' = dG0 + nH * (R T ln(10) pH + DH) - charge^2 * DH
        pseudoisomers = np.vstack([dG0s, np.array(self.nHs), np.array(self.zs)]).T
        dG0_prime_vector = pseudoisomers[:, 0] + \
                           pseudoisomers[:, 1] * (R * T * np.log(10) * pH + DH) - \
                           pseudoisomers[:, 2]**2 * DH

        return -R * T * logsumexp(dG0_prime_vector / (-R * T))

if __name__ == '__main__':
    print Compound.get_inchi(125)
