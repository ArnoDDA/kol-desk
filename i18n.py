"""English presentation of application-owned text; never translate user-authored fields."""
import json
import re
from pathlib import Path

CATALOG = json.loads((Path(__file__).resolve().parent / 'locales/en.json').read_text())
NON_ASCII = re.compile(r'[^\x00-\x7f]+')
ENUM_FIELDS = {'format', 'goal', 'platform'}
ENUM_VALUES = {'长视频', '短视频', '直播', '图文', '其他', '愿望单', '安装激活', '有效曝光', '留存玩家'}
AUTO_ACTIONS = {'project_created', 'project_updated', 'created', 'updated', 'selected', 'submitted'}


def english(text):
    if not isinstance(text, str):
        return text
    return NON_ASCII.sub(lambda m: CATALOG.get(m.group(), m.group()), text)


def canonical_option(value, options):
    if value in options:
        return value
    for option in options:
        if isinstance(value, str) and english(option).casefold() == value.casefold():
            return option
    return value


def localize_payload(value, local_user_id=None):
    if isinstance(value, list):
        return [localize_payload(item, local_user_id) for item in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, item in value.items():
        if key in ENUM_FIELDS and isinstance(item, str) and item in ENUM_VALUES:
            result[key] = english(item)
        elif key in {'error', 'reason', 'metric_label', 'label'} and isinstance(item, str):
            result[key] = english(item)
        elif key in {'blockers', 'warnings', 'gaps'} and isinstance(item, list):
            result[key] = [english(s) for s in item]
        elif key == 'basis' and 'estimated_credit' in value:
            result[key] = english(item)
        elif key == 'note' and value.get('action') in AUTO_ACTIONS:
            result[key] = english(item)
        elif key == 'name' and value.get('username') == '__local_workspace__':
            result[key] = 'Local workspace'
        elif key == 'user_name' and local_user_id and value.get('user_id') == local_user_id:
            result[key] = 'Local workspace'
        elif key in {'response', 'raw', 'payload'}:
            # Provider evidence and original request bodies must remain untouched.
            result[key] = item
        else:
            result[key] = localize_payload(item, local_user_id)
    return result
