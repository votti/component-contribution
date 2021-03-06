import types
import re
import kegg_errors
import numpy as np
from compound_cacher import CompoundCacher

class KeggReaction(object):

    def __init__(self, sparse, arrow='<=>', rid=None):
        for cid, coeff in sparse.iteritems():
            if type(cid) != types.IntType:
                raise ValueError('All keys in KeggReaction must be integers')
            if type(coeff) not in [types.FloatType, types.IntType]:
                raise ValueError('All values in KeggReaction must be integers or floats')
        self.sparse = sparse
        self.arrow = arrow
        self.rid = rid

    def keys(self):
        return self.sparse.keys()
        
    def iteritems(self):
        return self.sparse.iteritems()

    @staticmethod
    def parse_reaction_formula_side(s):
        """ 
            Parses the side formula, e.g. '2 C00001 + C00002 + 3 C00003'
            Ignores stoichiometry.
            
            Returns:
                The set of CIDs.
        """
        if s.strip() == "null":
            return {}
        
        compound_bag = {}
        for member in re.split('\s+\+\s+', s):
            tokens = member.split(None, 1)
            if len(tokens) == 1:
                amount = 1
                key = member
            else:
                try:
                    amount = float(tokens[0])
                except ValueError:
                    raise kegg_errors.KeggParseException(
                        "Non-specific reaction: %s" % s)
                key = tokens[1]
                
            if key[0] != 'C':
                raise kegg_errors.KeggNonCompoundException(
                    "Compound ID doesn't start with C: %s" % key)
            try:
                cid = int(key[1:])
                compound_bag[cid] = compound_bag.get(cid, 0) + amount
            except ValueError:
                raise kegg_errors.KeggParseException(
                    "Non-specific reaction: %s" % s)
        
        return compound_bag

    @staticmethod
    def parse_formula(formula, arrow='<=>'):
        """ 
            Parses a two-sided formula such as: 2 C00001 => C00002 + C00003 
            
            Return:
                The set of substrates, products and the direction of the reaction
        """
        tokens = formula.split(arrow)
        if len(tokens) < 2:
            raise ValueError('Reaction does not contain the arrow sign: ' + formula)
        if len(tokens) > 2:
            raise ValueError('Reaction contains more than one arrow sign: ' + formula)
        
        left = tokens[0].strip()
        right = tokens[1].strip()
        
        sparse_reaction = {}
        for cid, count in KeggReaction.parse_reaction_formula_side(left).iteritems():
            sparse_reaction[cid] = sparse_reaction.get(cid, 0) - count 

        for cid, count in KeggReaction.parse_reaction_formula_side(right).iteritems():
            sparse_reaction[cid] = sparse_reaction.get(cid, 0) + count 

        return KeggReaction(sparse_reaction, arrow)

    @staticmethod
    def write_compound_and_coeff(cid, coeff):
        comp = "C%05d" % cid
        if coeff == 1:
            return comp
        else:
            return "%g %s" % (coeff, comp)

    def write_formula(self):
        """String representation."""
        left = []
        right = []
        for cid, coeff in sorted(self.sparse.iteritems()):
            if coeff < 0:
                left.append(KeggReaction.write_compound_and_coeff(cid, -coeff))
            elif coeff > 0:
                right.append(KeggReaction.write_compound_and_coeff(cid, coeff))
        return "%s %s %s" % (' + '.join(left), self.arrow, ' + '.join(right))

    def is_balanced(self):
        cids = list(self.keys())
        coeffs = np.array([self.sparse[cid] for cid in cids], ndmin=2).T
    
        elements, Ematrix = CompoundCacher.getInstance().get_kegg_ematrix(cids)
        conserved = Ematrix.T * coeffs
        
        if np.any(np.isnan(conserved), 0):
            logging.debug('cannot test reaction balancing because of unspecific '
                          'compound formulas: %s' % self.write_formula())
            return True
        
        if np.any(conserved != 0, 0):
            logging.debug('unbalanced reaction: %s' % self.write_formula())
            for j in np.where(conserved[:, 0])[0].flat:
                logging.debug('there are %d more %s atoms on the right-hand side' %
                              (conserved[j, 0], elements[j]))
            return False

        return True
