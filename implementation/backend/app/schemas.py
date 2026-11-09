"""Strict response contracts. Source text and timestamps remain deterministic."""
def obj(properties):
    return {'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}
def array(items):
    return {'type':'array','items':items}
TEXT={'type':'string'}
INTEGER={'type':'integer'}
BOOL={'type':'boolean'}
REFS=array(TEXT)
HOOK=obj({'description':TEXT,'hook_type':TEXT,'evidence_block_ids':REFS})
ENDING=obj({'description':TEXT,'ending_type':TEXT,'open_question':TEXT,'evidence_block_ids':REFS,
            'resolution_evidence_block_ids':REFS})
SCENE=obj({'scene_id':TEXT,'summary':TEXT,'tags':array(TEXT),'hooks':array(HOOK),
           'endings':array(ENDING),'context_needed':array(TEXT)})
EPISODE=obj({'summary':TEXT,'scenes':array(SCENE)})
CUT=obj({'title':TEXT,'start_block_id':TEXT,'end_block_id':TEXT,'hook':TEXT,'cliffhanger':TEXT,
         'open_question':TEXT,'clip_tags':array(TEXT),'ending_tags':array(TEXT),'why_it_works':TEXT})
CUTS=obj({'candidates':array(CUT),'no_suitable_clip_reason':TEXT})
POINT_MAXIMUMS = {'hook': 30, 'clarity': 25, 'cliffhanger': 35, 'pacing': 10}
POINTS = obj({criterion: {'type': 'integer', 'minimum': 0, 'maximum': maximum}
              for criterion, maximum in POINT_MAXIMUMS.items()})
REVIEW=obj({'candidate_id':TEXT,'suitable':BOOL,'points':POINTS,
            'score_notes':obj({criterion:TEXT for criterion in POINT_MAXIMUMS}),
            'hook_evidence_block_ids':REFS,'ending_evidence_block_ids':REFS,
            'clarity_evidence_block_ids':REFS,'pacing_evidence_block_ids':REFS,
            'open_question':TEXT,'concerns':array(TEXT),'reason':TEXT})
REVIEWS=obj({'reviews':array(REVIEW)})

def response_format(prompt):
    if prompt.startswith('STAGE: PROMO_CUTS'):
        name,schema='promo_cuts',CUTS
    elif prompt.startswith('STAGE: PROMO_REVIEW'):
        name,schema='promo_reviews',REVIEWS
    else:
        name,schema='scene_analysis',EPISODE
    return {'type':'json_schema','json_schema':{'name':name,'strict':True,'schema':schema}}
