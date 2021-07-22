
import json
import wget
import os
import random
from sklearn.model_selection import train_test_split
import numpy as np
from torch.utils.data.dataset import random_split
import re
from string import punctuation

class TextPreprocess():
    """
    Text Preprocess module
    Support lowercase, removing punctuation, typo correction
    """
    def __init__(self, 
            lowercase=True, 
            remove_punctuation=True,
            ignore_punctuations="",
            typo_path=None):
        """
        Parameters
        ==========
        typo_path : str
            path of known typo dictionary
        """
        self.lowercase = lowercase
        self.typo_path = typo_path
        self.rmv_puncts = remove_punctuation
        self.punctuation = punctuation
        for ig_punc in ignore_punctuations:
            self.punctuation = self.punctuation.replace(ig_punc,"")
        self.rmv_puncts_regex = re.compile(r'[\s{}]+'.format(re.escape(self.punctuation)))
        
        if typo_path:
            self.typo2correction = self.load_typo2correction(typo_path)
        else:
            self.typo2correction = {}

    def load_typo2correction(self, typo_path):
        typo2correction = {}
        with open(typo_path, mode='r', encoding='utf-8') as f:
            lines = f.readlines()
            for line in lines:
                s = line.strip()
                tokens = s.split("||")
                value = "" if len(tokens) == 1 else tokens[1]
                typo2correction[tokens[0]] = value    

        return typo2correction 

    def remove_punctuation(self,phrase):
        phrase = self.rmv_puncts_regex.split(phrase)
        phrase = ' '.join(phrase).strip()

        return phrase

    def correct_spelling(self, phrase):
        phrase_tokens = phrase.split()
        phrase = ""

        for phrase_token in phrase_tokens:
            if phrase_token in self.typo2correction.keys():
                phrase_token = self.typo2correction[phrase_token]
            phrase += phrase_token + " "
       
        phrase = phrase.strip()
        return phrase

    def run(self, text):
        if self.lowercase:
            text = text.lower()

        if self.typo_path:
            text = self.correct_spelling(text)

        if self.rmv_puncts:
            text = self.remove_punctuation(text)

        text = text.strip()

        return text

#catch all suitable datasets on the website
def get_all_data(filename='../data/ontologies.jsonld'):
    specific_problem_ids=['rs','fix','eo','envo']# for some unkonwn reasons, rs.obo, fix.obo and eo.obo can not be downloaded;and envo has a strange problem
    urls = []
    ids = []
    with open(filename,mode='r',encoding='utf-8') as f:
        content = json.load(f)['ontologies']
        for i,entry in enumerate(content):
            id = entry['id']
            #every entry has an id, and we only need to consider the urls which are normalized as {id}.obo
            if 'products' in entry.keys():
                products = entry['products']
                
                for product in products:
                    if product['id']==id + '.obo' and id not in specific_problem_ids:
                        urls.append(product['ontology_purl'])
                        ids.append(id)
    
    #download relative files to data_dir, finnally we get 95 files
    #print(ids)
    data_dir = '../data/datasets'
    for i,(id,url) in  enumerate(zip(ids,urls)):
        #print(id)
        filename = id+'.obo'
        file = wget.download(url=url,out= os.path.join(data_dir,filename))

#given single file, construct corresponding graph of terms and its dictionary and query set
def load_data(filename='../../../data/datasets/cl.obo',migration_rate = 0.5, use_text_preprocesser = True):
    """
    args:
        migration_rate: decide the rate of the synonyms that conveyed to the dictionary set

        use text preprocesser: decide whether we process the data wtih lowercasing and removing punctuations
    
    returns:
        sorted_name_set:record of all the terms' names. no repeated element, in the manner of lexicographic order

        mention2id:map all mentions(names and synonyms of all terms) to ids, the name and synonyms with same term have the same id

        id2mention_group: map ids to their corresponding name and synonyms, the first element is always the name

        dict_set,query_set:list of （mention,id）, in the order of ids, later we split the query_set into train and test dataset;sorted by ids
        
        edges: list of tuples whose format is like(a,b), where a and b indicate the id of id of father_node and son_node respectively

    
    some basic process rules:
    1.To oavoid overlapping, we just abandon the synonyms which are totally same as their names
    2. Considering that some names appear twice or more, We abandon correspoding synonyms
    3.Some synonyms have more than one corresponding term, we just take the first time counts
    """
    text_processer = TextPreprocess() 
    name_list = []#record of all terms, rememeber some elements are repeated
    sorted_name_set = None
    mention2id = {}
    id2mention_group={}
    dict_set,query_set = [],[]
    edges=[] 

    with open(file=filename,mode='r',encoding='utf-8') as f:
        check_new_term = False
        lines = f.readlines()
        for i, line in enumerate(lines):
            if line[:6]=='[Term]':#starts with a [Term] 
                check_new_term = True
                continue
            if line[:1]=='\n':#ends with a '\n'
                check_new_term = False
                continue
            if check_new_term == True:
                if line[:5]=='name:':
                    name_list.append(text_processer.run(line[6:-1])if use_text_preprocesser else line[6:-1])
        
        name_count = {}
        
        #record the count of names in raw file
        for i,name in enumerate(name_list):
            name_count[name] = name_list.count(name)
        
        #build a mapping function of name2id, considering that some names appear twice or more, we remove the duplication and sort them
        sorted_name_set = sorted(list(set(name_list)))
        dict_set = [(name,i) for i,name in enumerate(sorted_name_set)]

        for i,name in enumerate(sorted_name_set):
            mention2id[name] = i
        
        #temporary variables for every term
        #construct a scipy csr matrix of edges and collect synonym pairs
        check_new_term = False
        check_new_name = False#remember that not every term has a name and we just take the terms with name count. Good news: names' locations are relatively above
        synonym_group = []#record the (synonym,id) of  current term
        name = ""
        iter_name = iter(name_list)


        for i,line in enumerate(lines):
            if line[:6]=='[Term]':#starts with a [Term] and ends with an '\n'
                check_new_term = True
                continue
            if line[:5]=='name:':

                check_new_name = True
                if check_new_term == True:
                    name = next(iter_name)
                continue
            if line[:1]=='\n':# signal the end of current term, deal with the synonym_group to construct the dictionary_set and query_set
                if check_new_term == True and check_new_name == True:
                    id = mention2id[name]
                    id2mention_group[id] = [name] + synonym_group# the first element will be name
                    
                    #split the symonym_group to dictionary and query
                    migration_num = int(len(synonym_group) * migration_rate)
                    dict_data,query_data = random_split(synonym_group, [migration_num, len(synonym_group) - migration_num], generator=torch.Generator().manual_seed(0)) 
                    dict_set+=[synonym_group[_] for _ in dict_data.indices]
                    query_set+=[synonym_group[_] for _ in query_data.indices]
                    

                check_new_term = False
                check_new_name = False
                synonym_group = []
                continue

            if check_new_term == True and check_new_name == True:
                #construct term graph
                if line[:5]=='is_a:':
                    entry = line.split(" ")
                    if '!' in entry:# some father_nodes are not divided by '!' and we abandon them
                        father_node = " ".join(entry[entry.index('!') + 1:])[:-1]
                        if father_node in sorted_name_set:#some father_nodes are not in concepts_list, and we abandon them.
                            edges.append((mention2id[father_node],mention2id[name]))
                
                # collect synonyms and to dictionary set and query set
                if line[:8]=='synonym:' and name_count[name] == 1: #anandon the situations that name appears more than once
                    start_pos = line.index("\"") + 1
                    end_pos = line[start_pos:].index("\"") + start_pos
                    synonym = text_processer.run(line[start_pos:end_pos]) if use_text_preprocesser else line[start_pos:end_pos]
                    if synonym==name:continue#filter these mentions that are literally equal to the node's name,make sure there is no verlap
                    if synonym in mention2id.keys():continue# only take the first time synonyms appears counts
                    id = mention2id[name]
                    synonym_group.append((synonym,id))
                    mention2id[synonym] = id
        
        dict_set = sorted(dict_set,key = lambda x:x[1])
        query_set = sorted(query_set,key = lambda x:x[1])
        """
        print(len(mention2id.items()))
        mentions = [x for group in id2mention_group.values() for x in group ]
        print(len(mentions))
        print(len(name_list))
        print(id2mention_group[0])
        print(len(query_set))
        print(len(dict_set))
        """

        return sorted_name_set,mention2id,id2mention_group,dict_set,query_set,edges




#split training and test data for one file that corresponds to the queries
def data_split(queries,is_unseen=True,test_size = 0.33,folds = 1,seed = 0):
    """
    args:
    is_unseen:if is_unseen==true, then the ids in training pairs and testing pairs will not overlap 
    returns:
    three folds of train,test datasets
    """
    datasets_folds=[]
    setup_seed(seed)
    #notice that we collect the (mention,concept) pairs in a order of all the concepts, so the same concepts will assemble together
    #as a result, we could remove all the (mention,concept) pairs with the same concept in an easy manner 
    mentions = [mention for (mention,id) in queries] 
    ids = [id for (mention,id) in queries]
    
    
    #random split
    if is_unseen == False:
        for fold in range(folds):
            mentions_train,mentions_test,ids_train,ids_test = train_test_split(
                mentions,ids,test_size=test_size)#have already set up seed 

            queries_train = [(mentions_train[i],ids_train[i]) for i in range(len(mentions_train))]
            queries_test = [(mentions_test[i,ids_test[i]]) for i in range(len(mentions_test))]
            datasets_folds.append((queries_train,queries_test))
    
    #random split, and the concepts in train set and test set will not overlap
    else:
        for fold in range(folds):
            mentions_train,mentions_test,ids_train,ids_test=mentions.copy(),[],ids.copy(),[]
            
            left_ids = sorted(list(set(ids)))
            while len(mentions_test) < len(mentions) * test_size:
                id = random.sample(left_ids,1)[0]
                
                start_index,end_index = ids.index(id), len(ids)-1 -  list(reversed(ids)).index(id)#the start index and the end index of the same concept

                for K in range(start_index,end_index+1):
                    mentions_test.append(mentions[K])
                    mentions_train.remove(mentions[K])
                    ids_test.append(id)
                    ids_train.remove(id)
                
                left_ids.remove(id)

            queries_train = [(mentions_train[i],ids_train[i]) for i in range(len(mentions_train))]
            queries_test = [(mentions_test[i],ids_test[i]) for i in range(len(mentions_test))]
            datasets_folds.append((queries_train,queries_test))

            #check overlap
            #for concept in concepts_test:
            #    if concept in concepts_train:
            #        print(concept)
                
    return datasets_folds



#generate negative samples if needed
def construct_positive_and_negative_pairs(concept_list,synonym_pairs,neg_posi_rate):
    """
    returns: positive pairs and negative pairs.And the number of negative samples is neg_posi_rate more than synonym pairs(positive samples)
    """
    negative_pairs = []
    for i,(mention,_) in enumerate(synonym_pairs):
        for _ in range(neg_posi_rate):
            concept = random.sample(concept_list,1)[0]
            while (mention,concept) in synonym_pairs or (mention,concept) in negative_pairs:#avoid overlapping
                concept = random.sample(concept_list,1)[0]
            negative_pairs.append((mention,concept))
    return synonym_pairs,negative_pairs

#set up seed         
def setup_seed(seed):
    random.seed(seed)
    np.random.seed(seed)        



if __name__ == '__main__':
    setup_seed(0)