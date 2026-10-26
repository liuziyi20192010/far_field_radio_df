"""Export public user/assistant messages only from explicit Codex JSONL paths.

No system/developer prompts, internal reasoning, tool arguments, or credentials
are exported. Original session files remain untouched outside the repository.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re


def public_text(text):
    text = re.sub(r'C:[/\\]Users[/\\][^/\\\s]+', 'C:/Users/redacted', text, flags=re.I)
    text = re.sub(r'https?://(?:192\.168\.|10\.|172\.(?:1[6-9]|2[0-9]|3[01])\.)[\d.]+(?::\d+)?',
                  'http://board.local', text)
    text = re.sub(r'(?i)(?:sk-[a-zA-Z0-9_-]{20,}|ghp_[a-zA-Z0-9]{20,})', '[redacted-token]', text)
    return text


def selected_history(entries, provenance, destination):
    """An optional destination policy keeps only the user-selected conversation.

    Match the first public user message, so a quotation of a conversation title
    in a different chat cannot accidentally authorize that chat for publication.
    Apply after merging as well, preventing a later export restoring other chats.
    """
    policy_file = destination / 'selection.json'
    project_root = Path(__file__).resolve().parents[2]
    if (not policy_file.is_file()
            and destination.resolve() == (project_root / 'report/interaction').resolve()):
        policy_file = project_root / 'build/config/interaction_selection.json'
    if not policy_file.is_file():
        return entries, provenance, None
    policy = json.loads(policy_file.read_text(encoding='utf-8'))
    prefix = policy.get('first_user_message_prefix')
    if not isinstance(prefix, str) or not prefix.strip():
        raise ValueError('Conversation selection requires a nonempty first-user prefix')
    first_users = {}
    for entry in entries:
        if entry['role'] == 'user':
            first_users.setdefault(entry['session_id'], entry['text'].lstrip())
    allowed = {sid for sid, first in first_users.items() if first.startswith(prefix)}
    if len(allowed) != 1:
        raise ValueError('Exactly one conversation must match the selected first-user prefix')
    return ([entry for entry in entries if entry['session_id'] in allowed],
            [source for source in provenance if source['session_id'] in allowed], prefix)


def export(sources, destination, replace=False):
    dest = Path(destination)
    dest.mkdir(parents=True, exist_ok=True)
    entries, provenance = [], []
    # Local session storage may later omit older chats. Preserve prior public
    # exports and their source hashes unless replacement is explicitly requested.
    if not replace and (dest / 'messages.jsonl').is_file():
        entries = [json.loads(line) for line in (dest / 'messages.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    if not replace and (dest / 'sources.json').is_file():
        provenance = json.loads((dest / 'sources.json').read_text(encoding='utf-8'))
    for source in sources:
        source = Path(source)
        raw = source.read_bytes()
        model, session = 'not_recorded', source.stem
        count = 0
        for number, line in enumerate(raw.decode('utf-8').splitlines(), 1):
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue  # live session's incomplete trailing line is not an event
            payload = event.get('payload', {})
            if event.get('type') == 'session_meta':
                session = payload.get('id', session)
            if event.get('type') == 'turn_context':
                model = payload.get('model', model)
            if event.get('type') != 'response_item' or payload.get('type') != 'message':
                continue
            role, channel = payload.get('role'), payload.get('channel')
            if role not in ('user', 'assistant') or channel == 'analysis':
                continue
            parts = []
            for content in payload.get('content', []):
                text = content.get('text', '')
                if not text or text.lstrip().startswith(('<environment_context>', '<recommended_plugins>',
                        '<external_codex_apps_open_page>', '<app_context>', '<permissions')):
                    continue
                parts.append(text)
            if not parts:
                continue
            entries.append({'timestamp_utc': event.get('timestamp'), 'session_id': session,
                            'source_line': number, 'model': model, 'role': role,
                            'channel': channel, 'text': public_text('\n'.join(parts))})
            count += 1
        provenance.append({'session_id': session, 'source_file': source.name,
                           'source_sha256': hashlib.sha256(raw).hexdigest(), 'messages_exported': count})
    unique = {}
    for entry in entries:
        if entry.get('role') not in ('user', 'assistant') or entry.get('channel') == 'analysis':
            continue
        entry['text'] = public_text(entry['text'])
        key = (entry.get('session_id'), entry.get('timestamp_utc'), entry.get('role'),
               entry.get('channel'), entry['text'])
        unique[key] = entry
    entries = sorted(unique.values(), key=lambda e: e['timestamp_utc'] or '')
    provenance = list({(e['session_id'], e['source_file'], e['source_sha256']): e for e in provenance}.values())
    entries, provenance, selected_title = selected_history(entries, provenance, dest)
    (dest / 'messages.jsonl').write_text(''.join(json.dumps(e, ensure_ascii=False) + '\n' for e in entries), encoding='utf-8')
    (dest / 'sources.json').write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    scope = ('只保留用户指定对话“' + selected_title + '”的公开消息；其他对话不纳入提交。'
             if selected_title else '保留所选来源的公开用户消息、模型 commentary/final。')
    body = ['# 大模型协作原始消息导出\n',
            '时间为 UTC；北京时间加 8 小时。' + scope +
            '排除内部推理、系统/开发者消息和工具参数。仅替换用户目录、局域网网址和令牌。'
            '不把后写总结伪装为历史回答。仅在同一选择范围内更新消息及来源哈希。\n']
    for e in entries:
        body.append(f"\n## {e['timestamp_utc']} | {e['role']} | {e['model']}\n\n"
                    f"来源 `{e['session_id']}`，JSONL 第 {e['source_line']} 行；通道 `{e['channel']}`。\n\n"
                    + e['text'] + '\n')
    (dest / 'transcript.md').write_text('\n'.join(body), encoding='utf-8')
    sessions = len({entry['session_id'] for entry in entries})
    print(f'INTERACTION_EXPORT_PASS: {len(entries)} public messages, {sessions} preserved sessions')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', action='append', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--replace', action='store_true', help='Explicitly replace instead of merging preserved public history')
    a = p.parse_args()
    export(a.source, a.output, a.replace)
