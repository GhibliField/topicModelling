import numpy as np, codecs, json,  cPickle as pickle, sys, random, itertools
from datetime import datetime
from sklearn import preprocessing
from sklearn.cluster import KMeans
from sklearn.metrics import precision_recall_fscore_support
from collections import Counter
from rpy2.robjects.packages import importr
import rpy2.robjects as robjects
utils = importr("copula")

class lda_gibbs_sampling_copula:
    def __init__(self, K=25, alpha=0.5, beta=0.5, copulaFamily="Frank", docs= None, V= None, copula_parameter=2):
        self.K = K
        self.copPar = copula_parameter
        self.family = copulaFamily
        self.alpha = alpha # parameter of topics prior
        self.beta = beta   # parameter of words prior
        self.docs = docs # a list of lists, each inner list contains the indexes of the words in a doc, e.g.: [[1,2,3],[2,3,5,8,7],[1, 5, 9, 10 ,2, 5]]
        self.V = V # how many different words in the vocabulary i.e., the number of the features of the corpus
        
        self.z_m_n = [] # topic assignements for each of the N words in the corpus. N: total number of words in the corpus (not the vocabulary size).
        self.n_m_z = np.zeros((len(self.docs), K), dtype=np.float64) + alpha     # |docs|xK topics: number of sentences assigned to topic z in document m  
        self.n_z_t = np.zeros((K, V), dtype=np.float64) + beta # (K topics) x |V| : number of times a word v is assigned to a topic z 
        self.n_z = np.zeros(K) + V * beta    # (K,) : overal number of words assigned to a topic z
        self.N = 0

        for m, doc in enumerate(docs):         # Initialization of the data structures I need.
            z_doc = []
            for sentence in doc: 
                self.N += len(sentence)
                z_n = []
                for t in sentence:
                    z = np.random.randint(0, K) # Randomly assign a topic to a sentence. Recall, topics have ids 0 ... K-1. randint: returns integers to [0,K[
                    z_n.append(z)                  # Keep track of the topic assigned 
                    self.n_m_z[m, z] += 1          # increase the number of words assigned to topic z in the m doc.
                    self.n_z_t[z, t] += 1   #  .... number of times a word is assigned to this particular topic
                    self.n_z[z] += 1   # increase the counter of words assigned to z topic
                z_doc.append(z_n)
            self.z_m_n.append(np.array(z_doc)) # update the array that keeps track of the topic assignements in the sentences of the corpus.

    def inference(self):
        """    The learning process. Here only one iteration over the data. 
               A loop will be calling this function for as many iterations as needed.     """
        for m, doc in enumerate(self.docs):
            z_n, n_m_z = self.z_m_n[m], self.n_m_z[m] #Take the topics of the words and the number of words assigned to each topic
            for sid, sentence in enumerate(doc): #Sentence stands for a chunk, that is contiguous words that are generated by topics that are bound. 
                # Get Sample from copula
                if len(sentence) > 1: # If the size of chunk is bigger than one, sample the copula, else back-off to standard LDA Gibbs sampling
                    command = "U = rnacopula(1, onacopula('%s', C(%s, 1:%d)))"%(self.family, self.copPar, len(sentence))
                    U = robjects.r(command)                
                for n, t in enumerate(sentence): # Dicsount the counters to sample new topics
                    z = z_n[sid][n]
                    n_m_z[z] -= 1
                    self.n_z_t[z, t] -= 1
                    self.n_z[z] -= 1
                for n, t in enumerate(sentence):
                    p = (self.n_z_t[:, t]+self.beta) * (n_m_z+self.alpha) / (self.n_z + self.V*self.beta) #Update probability distributions
                    p = p / p.sum() # normalize the updated distributions
                    if len(sentence)>1: # Copula mechanism over the words of a chunk (noun-phrase or sentence)
                        new_z = self.getTopicIndexOfCopulaSample(p, U[n]) 
                    else:
                        new_z = np.random.multinomial(1, p).argmax() # Back-off to Gibbs sampling if len(sentence) == 1 for speed.
                    z_n[sid][n] = new_z
                    n_m_z[new_z] += 1
                    self.n_z_t[new_z, t] += 1
                    self.n_z[new_z] += 1

    def getTopicIndexOfCopulaSample(self, probs, sample): #Probability integral transform: given a uniform sample from the copula, use the quantile $F^{-1}$ to tranform it to a sample from f
        cdf = 0
        for key, val in enumerate(probs):
            cdf += val
            if sample <= cdf:
                return key

    def heldOutPerplexity(self, docs, iterations):
        N, log_per, z_m_n = 0, 0, []
        n_m_z1, n_z_t, n_z = (np.zeros((len(docs), self.K)) + self.alpha), (np.zeros((self.K, self.V)) + self.beta), np.zeros(self.K)
        for m, doc in enumerate(docs):         # Initialization of the data structures I need.
            z_doc = []
            for sentence in doc:
                N += len(sentence)
                z_n = []
                for t in sentence:
                    z = np.random.randint(0, self.K) # Randomly assign a topic to a sentence. Recall, topics have ids 0 ... K-1. randint: returns integers to [0,K[
                    z_n.append(z)                  # Keep track of the topic assigned 
                    n_m_z1[m, z] += 1          # increase the number of words assigned to topic z in the m doc.
                    n_z_t[z, t] += 1   #  .... number of times a word is assigned to this particular topic
                    n_z[z] += 1   # increase the counter of words assigned to z topic
                z_doc.append(z_n)
            z_m_n.append(np.array(z_doc))
        for i in range(iterations):
            for m, doc in enumerate(docs):
                z_n, n_m_z = z_m_n[m], n_m_z1[m] #Take the topics of the words and the number of words assigned to each topic
                for sid, sentence in enumerate(doc):
                    if len(sentence) > 1:
                        command = "U = rnacopula(1, onacopula('%s', C(%s, 1:%d)))"%(self.family, self.copPar, len(sentence))
                        U = robjects.r(command)
                    for n, t in enumerate(sentence):
                        z = z_n[sid][n]
                        n_m_z[z] -= 1
                        n_z_t[z, t] -= 1
                        n_z[z] -= 1
                    for n, t in enumerate(sentence):
                        p = (self.n_z_t[:, t]+self.beta) * (n_m_z+self.alpha) / (self.n_z + self.V*self.beta)
                        p = p / p.sum()
                        if len(sentence)>1:
                            new_z = self.getTopicIndexOfCopulaSample(p, U[n])
                        else:
                            new_z = np.random.multinomial(1, p).argmax()
                        z_n[sid][n] = new_z
                        n_m_z[new_z] += 1
                        n_z_t[new_z, t] += 1
                        n_z[new_z] += 1

        phi = self.worddist()
        log_per = 0
        Kalpha = self.K * self.alpha
        for m, doc in enumerate(docs):
            theta = n_m_z1[m] / (sum([len(x) for x in doc]) + Kalpha)
            for key, val in enumerate(doc):
                for w in val:
                    log_per -= np.log(np.inner(phi[:,w], theta))
        return np.exp(log_per / N)
    

    def topicdist(self):
        topcDist = self.n_m_z / np.array([sum([len(y) for y in x]) for x in self.docs])[:, np.newaxis]
        return topcDist     


    def perplexity(self):
        docs = self.docs
        phi = self.worddist()
        log_per, N = 0, 0
        Kalpha = self.K * self.alpha
        for m, doc in enumerate(docs):
            theta = self.n_m_z[m] / (sum([len(x) for x in doc]) + Kalpha)
            for key, val in enumerate(doc):
                for w in val:
                    log_per -= np.log(np.inner(phi[:,w], theta))
        return np.exp(log_per / self.N)



    def worddist(self):
        """get topic-word distribution, \phi in Blei's paper. Returns the distribution of topics and words. (Z topics) x (V words)  """
        return self.n_z_t / self.n_z[:, np.newaxis]  #Normalize each line (lines are topics), with the number of words assigned to this topics to obtain probs.  *neaxis: Create an array of len = 1


