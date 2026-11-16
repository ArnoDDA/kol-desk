# Validation · 2026-11-16

## Verified locally

- 38 Python tests passed on macOS with Python 3.9.6.
- All Chinese and generated English JavaScript passed Node syntax checks.
- English asset regeneration is reproducible (`scripts/build_locales.py --check`).
- Both macOS launcher scripts passed shell syntax checks.
- Existing Chinese campaign information can be loaded, edited, and saved in the English UI without translating user names, notes, content evidence, or audience descriptions. Canonical formats and objectives survive switching back to Chinese.
- English CSV input, English CSV output, and English Markdown decision reports were checked through real local HTTP requests and temporary SQLite databases.
- Browser QA covered English campaign creation, provider setup with a synthetic key, search preview and credit confirmation, synthetic result display, shortlist import, note editing, and switching back to Chinese. The edited bilingual note and original Chinese creator name remained unchanged. No browser console warnings or errors were observed.
- The English search page was checked at a 390 px viewport; the document did not overflow horizontally. Temporary viewport overrides were reset.

## Regression coverage

The original 31 business and discovery tests cover complete/unknown fees, whole-selection budget approval, stale edits, approval invalidation and history, roles, sessions, request origin, atomic CSV imports, deduplication, spreadsheet formula safety, saved results, provider mapping, opaque IDs, cursor pagination, missing credentials, explicit credit consent, changed keys/prices, and failed searches without retries.

Seven additional release tests cover localized system fields without translating business data, reproducible English assets, English validation messages, create/edit/import/export/report round trips, startup health and language assets, unsupported billing and account privacy, and concurrent execution of the same search. The concurrency test confirms only one provider search is sent.

## Not established by these checks

- No real provider account, paid search, contact lookup, profile unlock, or purchase was used. Response fixtures validate our adapter behavior, not current upstream service availability or billing.
- The screenshot is an isolated synthetic QA workspace, not actual creator discovery.
- Windows launch script has not been tested on a Windows desktop. Linux compatibility is checked by GitHub Actions after upload; consult the repository run status.
- No multi-computer deployment, production load test, external security audit, or independent assessment of creator data quality was performed.

## 中文说明

本次本机验证共 38 项 Python 测试通过，并完成中英文脚本语法与浏览器验收。英文建项目、积分确认、合成搜索、加入备选、编辑备注及切回中文均已验证；业务原文保持不变。测试不使用真实供应商凭证，不发生真实付费搜索。Windows 桌面、多电脑部署、真实服务可用性和生产安全审计不在已验证范围内。
