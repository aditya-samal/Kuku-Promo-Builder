def annotation(parsed):
    return {'summary':'A person speaks in a room.','scenes':[{'scene_id':s['id'],'summary':'Conversation in a room.',
            'tags':['conversation'],'hooks':[],'endings':[],'context_needed':[]} for s in parsed['scenes']]}
