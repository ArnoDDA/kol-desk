"""English decision reports. User-entered text is preserved verbatim."""
import i18n


def decision_report_en(data, user, timestamp):
    def text(value):
        return str(value).replace('|', '\\|').replace('\r', '').replace('\n', ' / ')
    def known(value):
        return 'Unknown' if value is None or value == '' else text(value)
    def yes(value):
        return 'Yes' if value else 'No'
    p, s = data['project'], data['summary']
    lines = [f"# {text(p['name'])} · Creator partnership decision report", '',
             f"Exported: {timestamp} · By: {text(user['name'])}", '',
             f"Game: {text(p['game'])} · Market: {text(p['market'])} · Objective: {i18n.english(p['goal'])} · Format: {i18n.english(p['format'])}",
             f"Budget: {p['currency']} {p['budget']:,.2f}. All recorded fees and the maximum bonus are included.",
             f"Minimum target audience share: {known(p['min_audience_pct'])}% · Audience verification required: {yes(p['require_audience'])} · Paid media rights required: {yes(p['require_paid_rights'])}",
             f"Selection: {s['selected_count']} creators · Known costs in campaign currency: {p['currency']} {s['known_selected_cost']:,.2f}.",
             'Selection costs are complete.' if s['selection_complete'] else 'Some fees or currencies are unresolved. This is not a complete budget.', '',
             'Internal approval is a team decision, not creator acceptance or a signed contract. Forecasts are not actual campaign results.']
    if p['is_demo']:
        lines += ['', '**Synthetic sample: creators, quotes, and performance are not real.**']
    for d in data['candidates']:
        a, q = d['assessment'], d['quote']
        lines += ['', f"## {text(d['name'])} · {d['platform']}", '',
                  f"Status: {d['state']} · Revision: {d['version']} · In selection: {yes(d['selected'])}",
                  f"Profile/account: {known(d['profile_url'] or d['account_id'])}",
                  f"Readiness: {i18n.english(a['label'])} · Fit rationale: {known(d['fit_note'])}",
                  f"Content evidence: {known(d['source_url'])} · Reviewed: {known(d['evidence_date'])} · Samples: {known(d['evidence_note'])}",
                  f"Audience: {known(d['audience_market'])} · Share: {known(d['audience_pct'])}% · Verified: {yes(d['audience_verified'])} · Source: {known(d['audience_source'])}",
                  f"Quote: {q['currency']} · Known cost: {a['known_cost']:,.2f} · Maximum total: {known(a['max_cost'])}",
                  'Fee breakdown: ' + '; '.join(f"{label}: {q['currency']} {known(q[k])}" for label,k in [('Creator','fee'),('Usage','usage'),('Exclusivity','exclusivity_fee'),('Production/localization','production'),('Tax/agency/payment','tax'),('Bonus cap','bonus_cap')]),
                  f"Deliverables: {known(q['deliverables'])} · Rights: {known(q['rights'])} · Payment: {known(q['payment'])}",
                  f"Quoted: {known(q['quoted_at'])} · Valid until: {known(q['valid_until'])} · Availability/exclusivity: {known(d['terms_note'])}",
                  f"Forecast views: {known(q['expected_views'])} · Forecast actions: {known(q['expected_actions'])} · Cost/view: {known(a['forecast_cpv'])} · Cost/action: {known(a['forecast_cpa'])} ({q['currency']})",
                  f"Forecast evidence: {known(q['forecast_basis'])}",
                  'Before committing: ' + ('; '.join(i18n.english(x) for x in a['blockers']) or 'No identified blockers'),
                  'Notes: ' + ('; '.join(i18n.english(x) for x in a['warnings']) or 'None'),
                  f"Next step: {known(d['next_action'])} · Deadline: {known(d['due_date'])}"]
    lines += ['', '## Decision and change history', '']
    for e in reversed(data['events']):
        note = i18n.english(e['note']) if e['action'] in i18n.AUTO_ACTIONS else e['note']
        lines.append(f"- {e['created_at']} · {text(e['user_name'])} · {e['action']}: {text(note)}")
    return '\n'.join(lines) + '\n'
