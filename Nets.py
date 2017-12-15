import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.nn.init as I
from torch.autograd import Variable


class EmbedAttention(nn.Module):

    def __init__(self, att_size):
        super(EmbedAttention, self).__init__()
        self.att_w = nn.Linear(att_size,1,bias=False)

    def forward(self,input,len_s):
        att = self.att_w(input).squeeze(-1)
        out = self._masked_softmax(att,len_s).unsqueeze(-1)
        return out
        
    
    def _masked_softmax(self,mat,len_s):
        
        len_s = torch.FloatTensor(len_s).type_as(mat.data).long()
        idxes = torch.arange(0,int(len_s[0]),out=mat.data.new(int(len_s[0])).long()).unsqueeze(1)
        mask = Variable((idxes<len_s.unsqueeze(0)).float(),requires_grad=False)

        exp = torch.exp(mat) * mask
        sum_exp = exp.sum(0,True)+0.0001
     
        return exp/sum_exp.expand_as(exp)



class AttentionalBiRNN(nn.Module):

    def __init__(self, inp_size, hid_size, dropout=0, RNN_cell=nn.GRU):
        super(AttentionalBiRNN, self).__init__()
        
        self.natt = hid_size*2

        self.rnn = RNN_cell(input_size=inp_size,hidden_size=hid_size,num_layers=1,bias=True,batch_first=True,dropout=dropout,bidirectional=True)
        self.lin = nn.Linear(hid_size*2,self.natt)
        self.att_w = nn.Linear(self.natt,1,bias=False)
        self.emb_att = EmbedAttention(self.natt)

    
    def forward(self, packed_batch):
        
        rnn_sents,_ = self.rnn(packed_batch)
        enc_sents,len_s = torch.nn.utils.rnn.pad_packed_sequence(rnn_sents)

        emb_h = F.tanh(self.lin(enc_sents))

        attended = self.emb_att(emb_h,len_s) * enc_sents
        return attended.sum(0,True).squeeze(0)



class UIAttentionalBiRNN(AttentionalBiRNN):

    def __init__(self, inp_size, hid_size, dropout=0, RNN_cell=nn.GRU):

        super(UIAttentionalBiRNN, self).__init__(inp_size, hid_size, dropout, RNN_cell)
        
        self.register_buffer("mask",torch.FloatTensor())
        self.att_h = nn.Linear(inp_size*2+self.natt,self.natt,bias=True)
        
        
    def forward(self, packed_batch,user_embs,item_embs):
        
        rnn_sents,_ = self.rnn(packed_batch)
        enc_sents,len_s = torch.nn.utils.rnn.pad_packed_sequence(rnn_sents)

        uit = torch.cat([user_embs.expand_as(enc_sents),item_embs.expand_as(enc_sents),enc_sents],dim=-1)
        summed = F.tanh(self.att_h(uit))

        return torch.sum(enc_sents * self.emb_att(summed,len_s),0)



class HAN(nn.Module):

    def __init__(self, ntoken, num_class, emb_size=200, hid_size=50):
        super(HAN, self).__init__()

        self.embed = nn.Embedding(ntoken, emb_size,padding_idx=0)
        self.word = AttentionalBiGRU(emb_size, hid_size)
        self.sent = AttentionalBiGRU(hid_size*2, hid_size)

        self.emb_size = emb_size
        self.lin_out = nn.Linear(hid_size*2,num_class)
        self.register_buffer("reviews",torch.Tensor())

        
    def set_emb_tensor(self,emb_tensor):
        self.emb_size = emb_tensor.size(-1)
        self.embed.weight.data = emb_tensor

    
    def _reorder_sent(self,sents,sent_order,lr):

        revs = Variable(self._buffers["reviews"].resize_(len(lr),lr[0],sents.size(1)).fill_(0), requires_grad=False)
        
        for i,len_rev in enumerate(lr):
            rev_s = sent_order[i,:len_rev]
            revs[i,0:len_rev,:] = sents[rev_s]

        return revs
        
    
    def forward(self, batch_reviews,sent_order,ls,lr):

        emb_w = F.dropout(self.embed(batch_reviews),training=self.training)
        packed_sents = torch.nn.utils.rnn.pack_padded_sequence(emb_w, ls,batch_first=True)
        sent_embs = self.word(packed_sents)
        rev_embs = self._reorder_sent(sent_embs,sent_order,lr)
        packed_rev = torch.nn.utils.rnn.pack_padded_sequence(rev_embs, lr,batch_first=True)
        doc_embs = self.sent(packed_rev)
        out = self.lin_out(doc_embs)

        return out


class NSCUPA(nn.Module):

    def __init__(self, ntoken, nusers, nitems, num_class, emb_size=200, hid_size=50):
        super(NSCUPA, self).__init__()

        self.embed = nn.Embedding(ntoken, emb_size, padding_idx=0)

        self.users = nn.Embedding(nusers, emb_size)
        I.normal(self.users.weight.data,0.01,0.01)
        self.items = nn.Embedding(nitems, emb_size)
        I.normal(self.items.weight.data,0.01,0.01)


        self.word = UIAttentionalBiRNN(emb_size, emb_size//2)
        self.sent = UIAttentionalBiRNN(emb_size, emb_size//2)

        self.emb_size = emb_size
        self.lin_out = nn.Linear(emb_size,num_class)
        self.register_buffer("reviews",torch.Tensor())

    def set_emb_tensor(self,emb_tensor):
        self.emb_size = emb_tensor.size(-1)
        self.embed.weight.data = emb_tensor

    
    def _reorder_sent(self,sents,sent_order,lr):

        #revs = Variable(self._buffers["reviews"].resize_(len(lr),lr[0],sents.size(1)).fill_(0), requires_grad=False)
        
        sents = F.pad(sents,(0,0,1,0))
        #rev_s = sents[sent_order[-1]]
        revs = torch.cat([ sents[sent_order[i]].unsqueeze(0) for i,len_rev in enumerate(lr)],dim=0)
        #print(revs)
        return revs

        # for i,len_rev in enumerate(lr):
        #     rev_s = sent_order[i,:len_rev]
        #     revs[i,0:len_rev,:] = sents[rev_s]

            #print(sents[sent_order[i]])



        return revs
        
    
    def forward(self, batch_reviews,users,items,sent_order,ui_indexs,ls,lr):
        
        
        u = users[ui_indexs]
        i = items[ui_indexs]


        emb_w = F.dropout(self.embed(batch_reviews),training=self.training)
        emb_u = F.dropout(self.users(u),training=self.training)
        emb_i = F.dropout(self.items(i),training=self.training)
        
        packed_sents = torch.nn.utils.rnn.pack_padded_sequence(emb_w, ls,batch_first=True)
       

        sent_embs = self.word(packed_sents,emb_u,emb_i)
        rev_embs = self._reorder_sent(sent_embs,sent_order,lr)

        packed_rev = torch.nn.utils.rnn.pack_padded_sequence(rev_embs, lr,batch_first=True)

        emb_u = F.dropout(self.users(users),training=self.training)
        emb_i = F.dropout(self.items(items),training=self.training)

        doc_embs = self.sent(packed_rev,emb_u,emb_i)

        out = self.lin_out(doc_embs)

        return out




