// Activity Logs Page Handler

function setupLogsPage() {
    const btnRefresh = document.getElementById('btn-logs-refresh');
    const btnClear = document.getElementById('btn-logs-clear');
    const btnCopy = document.getElementById('btn-logs-copy');
    const sessionSel = document.getElementById('sel-logs-session');
    const levelSel = document.getElementById('sel-logs-level');
    const limitSel = document.getElementById('sel-logs-limit');

    if (btnRefresh) btnRefresh.onclick = () => { refreshLogSessions(true); };
    if (sessionSel) sessionSel.onchange = loadActivityLogs;
    if (levelSel) levelSel.onchange = loadActivityLogs;
    if (limitSel) limitSel.onchange = loadActivityLogs;

    if (btnClear) {
        btnClear.onclick = () => {
            const sessionFile = sessionSel ? sessionSel.value : '';
            if (confirm("Are you sure you want to clear this session log file?")) {
                backend.clear_activity_logs(sessionFile, (resStr) => {
                    const res = JSON.parse(resStr);
                    if (res.success) {
                        loadActivityLogs();
                    } else {
                        backend.show_error(res.error || "Failed to clear logs");
                    }
                });
            }
        };
    }

    if (btnCopy) {
        btnCopy.onclick = () => {
            const consoleBox = document.getElementById('log-console-box');
            if (consoleBox) {
                navigator.clipboard.writeText(consoleBox.textContent)
                    .then(() => alert("Logs copied to clipboard!"))
                    .catch(err => backend.show_error("Failed to copy: " + err));
            }
        };
    }

    refreshLogSessions();
}

function refreshLogSessions(triggerLoad = true) {
    const sessionSel = document.getElementById('sel-logs-session');
    if (!sessionSel || !backend || !backend.list_log_sessions) return;

    backend.list_log_sessions((resStr) => {
        try {
            const res = JSON.parse(resStr);
            if (res.success && res.sessions) {
                const currentVal = sessionSel.value;
                sessionSel.innerHTML = '';
                res.sessions.forEach(s => {
                    const opt = document.createElement('option');
                    opt.value = s.filename;
                    opt.textContent = s.label;
                    if (s.is_current) opt.selected = true;
                    sessionSel.appendChild(opt);
                });
                if (currentVal && sessionSel.querySelector(`option[value="${currentVal}"]`)) {
                    sessionSel.value = currentVal;
                }
                if (triggerLoad) loadActivityLogs();
            }
        } catch (e) {
            console.error("Failed to parse log sessions:", e);
        }
    });
}

function loadActivityLogs() {
    const sessionSel = document.getElementById('sel-logs-session');
    const levelSel = document.getElementById('sel-logs-level');
    const limitSel = document.getElementById('sel-logs-limit');
    const consoleBox = document.getElementById('log-console-box');
    const pathLbl = document.getElementById('lbl-log-path');
    const summaryLbl = document.getElementById('lbl-log-summary');

    if (!consoleBox) return;

    const sessionFile = sessionSel ? sessionSel.value : '';
    const level = levelSel ? levelSel.value : '';
    const limit = limitSel ? parseInt(limitSel.value) : 100;

    if (backend && backend.get_recent_activity_logs) {
        backend.get_recent_activity_logs(level, limit, sessionFile, (resStr) => {
            try {
                const res = JSON.parse(resStr);
                if (res.success) {
                    consoleBox.textContent = res.logs || "No logs match the filter criteria.";
                    if (pathLbl) pathLbl.textContent = res.path || "species_gen_activity.log";
                    if (summaryLbl) {
                        summaryLbl.textContent = `Showing ${res.displayed_entries || 0} of ${res.total_entries || 0} entries`;
                    }
                    consoleBox.scrollTop = consoleBox.scrollHeight;
                } else {
                    consoleBox.textContent = "Error loading logs: " + (res.error || "Unknown error");
                }
            } catch (e) {
                consoleBox.textContent = "Error parsing logs: " + e.message;
            }
        });
    }
}
