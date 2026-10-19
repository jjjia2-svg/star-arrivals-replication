import pandas as pd
CAUSE = {
# A: wrong department (not in the economics department)
**{k:'A_系归属错(不在经济系)' for k in [
 'A5057148289','A5066605209','A5113440291','A5086095616',
 'A5040957512','A5000195995',
 'A5053287006','A5050357458','A5069415850',
 'A5065344299','A5089364263','A5001701778','A5049010126','A5074137702','A5061523893',
 'A5033118098','A5126463985','A5007086439','A5005195196','A5004337400','A5072051358',
 'A5064512830','A5042616276','A5083945877','A5015052701','A5000248582','A5040485438','A5027276494',
 'A5024990189','A5090637418',
 'A5073251863','A5102902369','A5053497885']},
# B: wrong id assignment (author_id is another person / the merged-id subject is someone else)
**{k:'B_配号错(ID是另一个人)' for k in [
 'A5050120204','A5100386784','A5110954730',                      # anu
 'A5042115782',
 'A5041227235','A5043335933','A5101891170',                      # macquarie
 'A5013583966','A5108784289',                                     # melbourne
 'A5103122192','A5060168266','A5005221518','A5010518543','A5046637756','A5102819936', # sydney
 'A5100436731','A5030823472','A5101876653','A5087413363','A5101406272','A5086655719']},# uq
# C: no such person / not at the school in that year range
**{k:'C_查无此人或年段无交集' for k in [
 'A5051613817','A5036193836','A5089745005','A5065343528',
 'A5113577786','A5004767121','A5082598611','A5102447716','A5054240727']},
# D: visiting/part-time/adjunct, not a regular appointment
**{k:'D_访问或兼职(非在编)' for k in [
 'A5053325516','A5001689232','A5019358946','A5018510054',
 'A5005591120','A5110468588','A5056551664','A5065572953','A5032378120','A5059507519','A5076526695']},
}
R = pd.read_csv('rejected_persons.csv')
R['reject_cause'] = R['author_id'].map(CAUSE)
miss = R[R.reject_cause.isna()]
print('unmapped:', len(miss)); print(miss[['school','author_id','display_name']].to_string())
cols = list(R.columns); cols.insert(6, cols.pop(cols.index('reject_cause')))
R = R[cols]
R.to_csv('rejected_persons.csv', index=False)
print(R.reject_cause.value_counts().to_string())
print(); print(pd.crosstab(R.school, R.reject_cause).to_string())
