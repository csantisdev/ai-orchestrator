"""CSS del dashboard."""

from __future__ import annotations


def _build_css() -> str:
    return """\n    :root{
      --bg-base:#09090b;--bg-surface:#111827;--bg-elevated:#0c0c0e;
      --bg-input:#18181b;--bg-code:#0f172a;
      --border:#27272a;--border-subtle:#1f1f23;--border-faint:#18181b;
      --text-primary:#f8fafc;--text-secondary:#a1a1aa;
      --text-muted:#71717a;--text-faint:#52525b;
      --text-code:#e2e8f0;--text-detail:#d1d5db;
      --overlay-bg:rgba(0,0,0,.65);--shadow-panel:-4px 0 40px rgba(0,0,0,.6);
    }
    [data-theme="light"]{
      --bg-base:#f8fafc;--bg-surface:#ffffff;--bg-elevated:#f1f5f9;
      --bg-input:#f4f4f5;--bg-code:#f0f4f8;
      --border:#e4e4e7;--border-subtle:#e4e4e7;--border-faint:#e2e8f0;
      --text-primary:#0f172a;--text-secondary:#52525b;
      --text-muted:#71717a;--text-faint:#a1a1aa;
      --text-code:#1e293b;--text-detail:#374151;
      --overlay-bg:rgba(0,0,0,.35);--shadow-panel:-4px 0 40px rgba(0,0,0,.1);
    }
    [data-theme="midnight"]{
      --bg-base:#0a0e1a;--bg-surface:#0f1629;--bg-elevated:#070b14;
      --bg-input:#141d35;--bg-code:#080c18;
      --border:#1e2d50;--border-subtle:#162040;--border-faint:#141d35;
      --text-primary:#e2e8f0;--text-secondary:#94a3b8;
      --text-muted:#64748b;--text-faint:#475569;
      --text-code:#cbd5e1;--text-detail:#b0bec5;
      --overlay-bg:rgba(0,0,0,.75);--shadow-panel:-4px 0 40px rgba(0,0,0,.7);
    }
    [data-theme="nord"]{
      --bg-base:#2e3440;--bg-surface:#3b4252;--bg-elevated:#292e39;
      --bg-input:#434c5e;--bg-code:#252a35;
      --border:#4c566a;--border-subtle:#434c5e;--border-faint:#3b4252;
      --text-primary:#eceff4;--text-secondary:#d8dee9;
      --text-muted:#a8b2c0;--text-faint:#7a8698;
      --text-code:#d8dee9;--text-detail:#c5ccd8;
      --overlay-bg:rgba(0,0,0,.55);--shadow-panel:-4px 0 40px rgba(0,0,0,.45);
    }
    [data-theme="espresso"]{
      --bg-base:#1c1410;--bg-surface:#261c14;--bg-elevated:#160f0a;
      --bg-input:#2e2018;--bg-code:#120d08;
      --border:#3d2e20;--border-subtle:#2d2218;--border-faint:#2e2018;
      --text-primary:#f5e6cf;--text-secondary:#c8a880;
      --text-muted:#8a7055;--text-faint:#6b5540;
      --text-code:#e8d5b0;--text-detail:#d4bc95;
      --overlay-bg:rgba(0,0,0,.7);--shadow-panel:-4px 0 40px rgba(0,0,0,.6);
    }
    [data-theme="a11y"]{
      --bg-base:#000000;--bg-surface:#0d0d0d;--bg-elevated:#000000;
      --bg-input:#141414;--bg-code:#000000;
      --border:#ffffff;--border-subtle:#cccccc;--border-faint:#999999;
      --text-primary:#ffffff;--text-secondary:#f0f0f0;
      --text-muted:#dddddd;--text-faint:#bbbbbb;
      --text-code:#ffffff;--text-detail:#eeeeee;
      --overlay-bg:rgba(0,0,0,.92);--shadow-panel:-4px 0 40px rgba(255,255,255,.12);
    }
    [data-theme="a11y"] *{letter-spacing:.03em}
    [data-theme="a11y"] body{font-size:15px}
    [data-theme="a11y"] select,
    [data-theme="a11y"] input,
    [data-theme="a11y"] textarea{border-width:2px;font-size:14px}
    [data-theme="a11y"] .btn{outline:2px solid currentColor;outline-offset:2px}
    [data-theme="a11y"] *:focus-visible{outline:3px solid #ffff00;outline-offset:2px}
    [data-theme="a11y"] a{text-decoration:underline}
    [data-theme="a11y"] .badge{outline:2px solid currentColor;outline-offset:1px;font-weight:700}
    [data-theme="a11y"] .badge-running{background:rgba(0,120,255,.25);color:#60b0ff}
    [data-theme="a11y"] .badge-pending{background:rgba(255,180,0,.25);color:#ffcc00}
    [data-theme="a11y"] .badge-failed{background:rgba(255,120,0,.25);color:#ff8800}
    [data-theme="a11y"] thead tr{border-top:2px solid var(--border);border-bottom:2px solid var(--border)}
    [data-theme="a11y"] tbody tr{border-bottom:1px solid var(--border-subtle)}
    [data-theme="a11y"] tbody tr:hover{background:rgba(255,255,255,.08);outline:2px solid var(--border);outline-offset:-2px}
    [data-theme="a11y"] .card{border-width:2px}
    [data-theme="a11y"] .panel{border-width:2px}
    [data-theme="a11y"] .detail-panel{border-left-width:3px}
    *{box-sizing:border-box;margin:0;padding:0}
    body{font-family:'Inter',system-ui,sans-serif;background:var(--bg-base);color:var(--text-primary);-webkit-font-smoothing:antialiased;padding-bottom:48px}
    .activity-bar{position:fixed;bottom:0;left:0;right:0;background:var(--bg-elevated);border-top:1px solid var(--border);z-index:200;font-family:'JetBrains Mono',monospace}
    .activity-hdr{display:flex;align-items:center;height:40px;user-select:none;transition:background .1s}
    .act-left{display:flex;align-items:center;gap:10px;flex:1;cursor:pointer;padding:0 0 0 16px;height:100%;overflow:hidden;min-width:0}
    .act-left:hover{background:var(--bg-surface)}
    .act-dot{width:7px;height:7px;border-radius:50%;background:var(--border);flex-shrink:0;transition:background .2s}
    .act-dot.live{background:#22c55e}
    .act-dot.pulse{animation:_adot .6s ease-in-out 3}
    @keyframes _adot{0%,100%{opacity:1}50%{opacity:.2}}
    .act-title{font-size:10px;font-weight:700;color:var(--text-muted);text-transform:uppercase;letter-spacing:.7px;flex-shrink:0}
    .act-summary{font-size:11px;color:var(--text-faint);flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .act-toggle{font-size:10px;color:var(--text-faint);flex-shrink:0;cursor:pointer;padding:0 12px 0 8px;height:100%;display:flex;align-items:center}
    .act-actions{display:flex;align-items:center;gap:4px;flex-shrink:0;padding:0 10px;border-left:1px solid var(--border)}
    .act-btn{font-size:10px;font-weight:600;font-family:'JetBrains Mono',monospace;padding:0 8px;border-radius:4px;border:1px solid var(--border);background:var(--bg-surface);color:var(--text-muted);cursor:pointer;transition:all .15s;white-space:nowrap;height:22px;letter-spacing:.2px;line-height:22px}
    .act-btn:hover:not(:disabled){background:var(--bg-input);color:var(--text-primary);border-color:var(--text-muted)}
    .act-btn:disabled{opacity:.4;cursor:not-allowed}
    .act-btn.running{border-color:#22c55e;color:#22c55e;animation:_adot .8s ease-in-out infinite}
    .act-btn-wrap{position:relative;display:flex;align-items:center}
    .act-btn-split{border-radius:4px 0 0 4px!important;border-right:none!important}
    .act-btn-arr{border-radius:0 4px 4px 0!important;padding:0 5px!important;border-left:1px solid var(--bg-input)!important}
    .act-dropdown{position:absolute;bottom:calc(100% + 6px);right:0;background:var(--bg-elevated);border:1px solid var(--border);border-radius:6px;padding:4px;min-width:180px;z-index:500;display:none;box-shadow:0 -4px 16px rgba(0,0,0,.35)}
    .act-dropdown.open{display:block}
    .act-dropdown button{display:block;width:100%;text-align:left;padding:6px 10px;font-size:11px;font-family:'JetBrains Mono',monospace;background:none;border:none;color:var(--text-primary);cursor:pointer;border-radius:4px;white-space:nowrap}
    .act-dropdown button:hover{background:var(--bg-surface)}
    .tr-row.tr-warn .tr-icon{color:#f59e0b}
    #activity-log{max-height:200px;overflow-y:auto;border-top:1px solid var(--bg-input)}
    .tr-row{display:grid;grid-template-columns:80px 44px 14px 1fr 64px;gap:8px;padding:4px 16px;align-items:center;font-size:11px;border-bottom:1px solid var(--bg-elevated)}
    .tr-ts{color:var(--border);font-variant-numeric:tabular-nums}
    .tr-run{color:var(--text-faint);text-align:right}
    .tr-icon{text-align:center;font-size:12px}
    .tr-name{color:var(--text-muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .tr-dur{color:var(--text-faint);text-align:right;font-variant-numeric:tabular-nums}
    .tr-running .tr-icon{color:#f59e0b}.tr-running .tr-name{color:var(--text-primary)}
    .tr-done .tr-icon{color:#22c55e}
    .tr-error .tr-icon{color:#f87171}.tr-error .tr-name{color:#f87171}
    .header{background:var(--bg-surface);border-bottom:1px solid var(--border);color:var(--text-primary);padding:14px 24px;display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}
    .header h1{font-size:16px;font-weight:700;letter-spacing:-.4px;color:var(--text-primary)}
    .header .meta{font-size:11px;color:var(--text-muted)}
    .container{max-width:1500px;margin:0 auto;padding:20px 16px}
    .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:20px}
    .card{background:var(--bg-surface);border-radius:16px;border:1px solid var(--border);padding:18px}
    .card .label{font-size:10px;text-transform:uppercase;letter-spacing:.7px;color:var(--text-muted);font-weight:600;margin-bottom:8px}
    .card .value{font-size:28px;font-weight:700;color:var(--text-primary);line-height:1}
    .card .sub{font-size:11px;color:var(--text-faint);margin-top:5px}
    .grid-charts{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px;margin-bottom:20px}
    .panel{background:var(--bg-surface);border-radius:16px;border:1px solid var(--border);padding:18px}
    .panel h2{font-size:10px;font-weight:700;color:var(--text-muted);margin-bottom:14px;text-transform:uppercase;letter-spacing:.7px}
    .toolbar{display:flex;align-items:center;gap:10px;margin-bottom:12px;flex-wrap:wrap}
    select,input,textarea{border:1px solid var(--border);border-radius:8px;padding:7px 12px;font-size:13px;background:var(--bg-input);color:var(--text-primary);font-family:inherit}
    textarea{width:100%;min-height:80px;resize:vertical}
    select:focus,input:focus,textarea:focus{outline:none;border-color:#22c55e}
    .btn{padding:7px 16px;border-radius:8px;border:none;font-size:13px;font-weight:600;cursor:pointer;transition:opacity .15s}
    .btn-primary{background:#22c55e;color:#09090b}
    .btn-primary:hover{opacity:.85}
    .btn-secondary{background:var(--bg-input);color:var(--text-primary);border:1px solid var(--border)}
    .btn-secondary:hover{background:var(--border)}
    table{width:100%;border-collapse:collapse}
    thead tr{background:var(--bg-elevated);border-bottom:1px solid var(--border)}
    th{padding:9px 12px;text-align:left;font-size:10px;text-transform:uppercase;letter-spacing:.7px;color:var(--text-muted);font-weight:600;white-space:nowrap}
    tbody tr{border-bottom:1px solid var(--border-faint);transition:background .1s}
    tbody tr:hover{background:var(--bg-input)}
    .empty{text-align:center;padding:40px;color:var(--text-muted);font-size:14px}
    .badge{display:inline-block;padding:2px 8px;border-radius:20px;font-size:11px;font-weight:600}
    .badge-running{background:rgba(56,189,248,0.12);color:#38bdf8;animation:pulse 1.5s ease-in-out infinite}
    .badge-pending{background:rgba(251,191,36,0.12);color:#fcd34d}
    .badge-failed{background:rgba(248,113,113,0.12);color:#f87171}
    @keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
    .sender-panel{background:var(--bg-surface);border-radius:16px;border:1px solid var(--border);padding:18px;margin-bottom:20px;display:none}
    .sender-panel.open{display:block}
    .sender-form{display:grid;grid-template-columns:1fr 1fr;gap:12px}
    @media(max-width:700px){.sender-form{grid-template-columns:1fr}}
    .sender-form .full{grid-column:1/-1}
    .detail-overlay{display:none;position:fixed;inset:0;background:var(--overlay-bg);z-index:100;backdrop-filter:blur(3px)}
    .detail-overlay.open{display:flex;align-items:flex-start;justify-content:flex-end}
    .detail-panel{background:var(--bg-surface);width:min(660px,95vw);height:100vh;overflow-y:auto;padding:24px;box-shadow:var(--shadow-panel);border-left:1px solid var(--border)}
    .detail-panel h3{font-size:15px;font-weight:700;margin-bottom:16px;color:var(--text-primary)}
    .detail-section{margin-bottom:18px}
    .detail-section label{display:block;font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.7px;color:var(--text-muted);margin-bottom:8px}
    .detail-section pre{background:var(--bg-code);border:1px solid var(--border);border-radius:12px;padding:14px;font-size:12px;white-space:pre-wrap;word-break:break-word;max-height:320px;overflow-y:auto;font-family:'JetBrains Mono','Consolas',monospace;color:var(--text-code);line-height:1.65}
    .budget-bar{height:5px;background:var(--border);border-radius:3px;overflow:hidden;margin-top:8px}
    .budget-fill{height:100%;border-radius:3px;transition:width .4s}
    .close-btn{float:right;background:none;border:none;font-size:20px;cursor:pointer;color:var(--text-muted);padding:0 4px}
    .close-btn:hover{color:var(--text-primary)}
    .spinner{display:inline-block;width:14px;height:14px;border:2px solid var(--border);border-top-color:#22c55e;border-radius:50%;animation:spin .8s linear infinite;vertical-align:middle}
    @keyframes spin{to{transform:rotate(360deg)}}
    #toast{position:fixed;bottom:20px;right:20px;background:var(--bg-input);color:var(--text-primary);border:1px solid var(--border);padding:10px 18px;border-radius:10px;font-size:13px;display:none;z-index:200;box-shadow:0 8px 24px rgba(0,0,0,.5)}
    .tabnav{background:var(--bg-surface);border-bottom:1px solid var(--border)}
    .tabnav-inner{max-width:1500px;margin:0 auto;padding:0 16px;display:flex;gap:2px}
    .tab-btn{background:none;border:none;border-bottom:2px solid transparent;color:var(--text-muted);font-size:13px;font-weight:500;padding:12px 14px;cursor:pointer;font-family:inherit;transition:color .15s,border-color .15s}
    .tab-btn:hover{color:var(--text-primary)}
    .tab-active{color:var(--text-primary);border-bottom-color:#22c55e}
    .insp-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:20px}
    .insp-stat{background:var(--bg-input);border:1px solid var(--border);border-radius:12px;padding:14px}
    .insp-stat .col-name{font-size:10px;text-transform:uppercase;letter-spacing:.7px;color:var(--text-muted);margin-bottom:8px;font-weight:600}
    .insp-stat .col-count{font-size:26px;font-weight:700;color:var(--text-primary);line-height:1}
    .insp-stat .col-sub{font-size:11px;color:var(--text-faint);margin-top:4px}
    .insp-stat .col-projects{margin-top:10px;border-top:1px solid var(--border);padding-top:8px}
    .insp-stat .col-proj-row{display:flex;justify-content:space-between;font-size:11px;padding:3px 0;border-bottom:1px solid var(--border-subtle)}
    .chip{background:var(--bg-input);color:var(--text-secondary);padding:3px 10px;border-radius:20px;font-size:11px}
    .chip-mono{background:var(--bg-input);color:var(--text-secondary);padding:3px 10px;border-radius:20px;font-size:11px;font-family:'JetBrains Mono',monospace}
    .td-ts{padding:9px 12px;color:var(--text-faint);font-size:11px;white-space:nowrap;font-family:'JetBrains Mono',monospace;font-variant-numeric:tabular-nums}
    .td-project{padding:9px 12px;font-weight:600;font-size:13px;color:var(--text-primary)}
    .td-muted{padding:9px 12px;font-size:12px;color:var(--text-muted)}
    .ctx-card{background:var(--bg-input);border:1px solid var(--border);border-radius:12px;padding:14px;margin-bottom:10px}
    .ctx-desc{font-size:12px;color:var(--text-muted);margin-bottom:10px;line-height:1.5}
    .step-idx{font-size:11px;font-weight:700;color:var(--text-faint);min-width:18px;text-align:center;font-family:'JetBrains Mono',monospace}
    .step-title{font-size:12px;color:var(--text-detail);flex:1}
    .ctx-step-btn{background:none;border:1px solid var(--border);border-radius:6px;color:var(--text-muted);font-size:11px;padding:2px 7px;cursor:pointer;font-family:inherit;line-height:1.4;flex-shrink:0;transition:background .12s,color .12s}
    .ctx-step-btn:hover{background:var(--bg-surface);color:var(--text-primary)}
    .ctx-step-advance:hover{border-color:#22c55e;color:#22c55e}
    .ctx-step-skip:hover{border-color:#f59e0b;color:#f59e0b}
    .ctx-play-btn{border-color:#38bdf8;color:#38bdf8;font-weight:700}
    .ctx-play-btn:hover{background:rgba(56,189,248,0.12);border-color:#38bdf8;color:#38bdf8}
    .ctx-play-btn:disabled{opacity:.4;cursor:default}
    .ctx-delete-btn{color:var(--text-faint);border-color:transparent}
    .ctx-delete-btn:hover{border-color:#f87171;color:#f87171;background:rgba(248,113,113,0.10)}
    .pagination-bar{display:flex;align-items:center;gap:6px;padding:10px 0 4px;flex-wrap:wrap}
    .pg-btn{background:var(--bg-input);border:1px solid var(--border);border-radius:6px;color:var(--text-muted);font-size:11px;padding:3px 9px;cursor:pointer;font-family:inherit;transition:background .12s}
    .pg-btn:hover:not(:disabled){background:var(--border);color:var(--text-primary)}
    .pg-btn:disabled{opacity:.35;cursor:default}
    .pg-btn-active{background:#22c55e;color:#09090b;border-color:#22c55e}
    .pg-btn-active:hover{background:#22c55e}
    .budget-meta{display:flex;justify-content:space-between;font-size:12px;color:var(--text-muted);margin-bottom:6px}
    .detail-text{font-size:13px;color:var(--text-secondary);line-height:1.5}
    .detail-thead-row{color:var(--text-faint);border-bottom:1px solid var(--border)}
    .detail-tbody-row{border-bottom:1px solid var(--border-faint)}
    .td-sm{padding:5px 8px}
    .td-sm-ts{padding:5px 8px;color:var(--text-faint);white-space:nowrap;font-family:'JetBrains Mono',monospace}
    .td-sm-text{padding:5px 8px;color:var(--text-detail)}
    .td-sm-muted{padding:5px 8px;color:var(--text-secondary)}
    .td-sm-mono{padding:5px 8px;font-weight:600;color:var(--text-primary);font-family:'JetBrains Mono',monospace}
    .theme-btn{background:none;border:1px solid var(--border);border-radius:6px;color:var(--text-muted);font-size:13px;padding:4px 10px;cursor:pointer;font-family:inherit;transition:color .15s,border-color .15s}
    .theme-btn:hover{color:var(--text-primary);border-color:var(--text-muted)}
    .text-muted{color:var(--text-muted)}
    .text-faint{color:var(--text-faint)}
    .text-primary{color:var(--text-primary)}
"""
