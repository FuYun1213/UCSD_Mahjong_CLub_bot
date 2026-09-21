"""Read-time current-name projection; stable IDs and stored audit snapshots stay intact."""
from copy import deepcopy


def with_registered_names(value, profiles):
    result = deepcopy(value)
    names = {str(p['id']): p['name'] for p in profiles if p.get('id') is not None and p.get('name')}
    avatars = {str(p['id']): p.get('avatar', '') for p in profiles if p.get('id') is not None}

    def aliases(node):
        if isinstance(node, list):
            for item in node:
                aliases(item)
        elif isinstance(node, dict):
            linked = str(node.get('account_id', ''))
            if linked in names and node.get('id') is not None:
                names[str(node['id'])] = names[linked]
                avatars[str(node['id'])] = avatars.get(linked, '')
            for item in node.values():
                aliases(item)

    def rewrite(node):
        if isinstance(node, list):
            for item in node:
                rewrite(item)
        elif isinstance(node, dict):
            uid = str(node.get('account_id') or node.get('user_id') or node.get('id') or '')
            if uid in names:
                if 'name' in node and not any(k in node for k in ('rounds', 'capacity', 'score_table_id')):
                    node['name'] = names[uid]
                    if avatars.get(uid) or 'avatar' in node:
                        node['avatar'] = avatars.get(uid, '')
                if 'user_name' in node:
                    node['user_name'] = names[uid]
            for key, label in [('actor_id', 'actor_name'), ('uploader_id', 'uploader_name'), ('added_by_user_id', 'added_by_name'), ('created_by', 'creator_name')]:
                if key in node:
                    node[label] = names.get(str(node[key]), node.get(label) or 'Unavailable player')
            for item in list(node.values()):
                rewrite(item)

    aliases(result)
    rewrite(result)
    return result
