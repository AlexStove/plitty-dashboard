// Auto-hide loader immediately
try {
    const earlyLoader = document.getElementById("pwa-loader");
    if (earlyLoader) {
        earlyLoader.style.opacity = "0";
        earlyLoader.style.pointerEvents = "none";
        setTimeout(() => { earlyLoader.style.display = "none"; }, 300);
    }
} catch(e) {}

// app.js
// Firebase Config configuration
const firebaseConfig = {
    apiKey: "AIzaSyA30QS2wxInEvKuK4mcgcCF6w43aGWc0Vo",
    authDomain: "plita-1c1c7.firebaseapp.com",
    databaseURL: "https://plita-1c1c7-default-rtdb.firebaseio.com/",
    projectId: "plita-1c1c7",
    storageBucket: "plita-1c1c7.firebasestorage.app",
    messagingSenderId: "1090198491726",
    appId: "1:1090198491726:web:88634232fd67994b7e691f",
    measurementId: "G-T9ERQBFEQK"
};

// Initialize Firebase
firebase.initializeApp(firebaseConfig);
const database = firebase.database();
// Remote Error Logging for debugging PWAs on smartphones
window.onerror = function(message, source, lineno, colno, error) {
    const errText = `JS Error: ${message} at ${source}:${lineno}:${colno}`;
    console.error(errText);
    try {
        database.ref("js_error").set({
            error: errText,
            timestamp: Date.now()
        });
    } catch(e) {}
};
// Full BRES list (23 accounts remaining)
const bresAccounts = [
    "@beatrizalvep2", "@dzmitry.saksonau", "@lariimba1", "@joonlyvibe",
    "@jamoremiller", "@waveanlyy", "@ariana.mells", "@exclusive_tunes6",
    "@futurehits59", "@fanlafana", "@funimbfaun", "@imbalarifun",
    "@leshaplita", "@genius", "@imaginedragons", "@coldplay",
    "@onedirection", "@gorillaz", "@queen", "@billboard",
    "@linkinpark", "@brunomars", "@charlieputh"
].join(" ");

// Elements Cache
const timeEl = document.getElementById("current-time");
const devicesCountEl = document.getElementById("devices-count");
const statusBadgeEl = document.getElementById("status-badge");
const runProgressCardEl = document.getElementById("run-progress-card");
const runTimerEl = document.getElementById("run-timer");
const etcValEl = document.getElementById("etc-val");
const progressFillEl = document.getElementById("progress-fill");
const progressPercentageEl = document.getElementById("progress-percentage");
const progressCircleEl = document.getElementById("progress-circle");
const circleNumEl = document.getElementById("circle-num");
const activeDevicesBadgeEl = document.getElementById("active-devices-badge");
const devicesGridEl = document.getElementById("devices-grid");
const terminalContentEl = document.getElementById("terminal-content");
const btnActionEl = document.getElementById("btn-action");
const btnInsertBresEl = document.getElementById("btn-insert-bres");
const accountsEditorGroupEl = document.getElementById("accounts-editor-group");
const targetAccountsEl = document.getElementById("target-accounts");
const btnCopyLogEl = document.getElementById("btn-copy-log");
const btnShowLogsEl = document.getElementById("btn-show-logs");
const btnCloseLogsEl = document.getElementById("btn-close-logs");
const logsModalEl = document.getElementById("logs-modal");

// Report Elements
const reportModalEl = document.getElementById("report-modal");
const btnCloseReportEl = document.getElementById("btn-close-report");
const reportScriptEl = document.getElementById("report-script");
const reportStatusEl = document.getElementById("report-status");
const reportDurationEl = document.getElementById("report-duration");
const reportCirclesEl = document.getElementById("report-circles");
const reportDevicesEl = document.getElementById("report-devices");
const reportErrorsEl = document.getElementById("report-errors");

// Confirm Modal Elements (with self-healing fallback for cached HTML)
let confirmModalEl = document.getElementById("confirm-modal");
let confirmTextEl = document.getElementById("confirm-text");
let btnConfirmYesEl = document.getElementById("btn-confirm-yes");
let btnConfirmNoEl = document.getElementById("btn-confirm-no");

if (!confirmModalEl) {
    console.log("Confirmation modal HTML missing (old cache). Creating dynamically...");
    confirmModalEl = document.createElement("div");
    confirmModalEl.id = "confirm-modal";
    confirmModalEl.className = "modal-overlay hidden";
    confirmModalEl.innerHTML = `
        <div class="modal-card report-card">
            <div class="modal-header">
                <span class="modal-title">⚠️ ПОДТВЕРЖДЕНИЕ</span>
            </div>
            <div class="report-content" style="text-align: center; font-size: 13px; font-weight: bold; color: var(--pink-dark); margin: 10px 0;">
                <div id="confirm-text">-</div>
            </div>
            <div style="display: flex; gap: 10px; width: 100%;">
                <button type="button" id="btn-confirm-no" class="stop-btn" style="flex: 1; border-radius: 12px; padding: 10px 0; font-size: 12px; font-weight: bold; background: rgba(255,255,255,0.05); color: #ffffff; border: 1px solid rgba(255,255,255,0.1);">ОТМЕНА</button>
                <button type="button" id="btn-confirm-yes" class="stop-btn" style="flex: 1; border-radius: 12px; padding: 10px 0; font-size: 12px; font-weight: bold; background: var(--pink-light); color: var(--pink-dark); border: 1.5px solid rgba(255, 45, 85, 0.25);">ЗАПУСТИТЬ</button>
            </div>
        </div>
    `;
    document.body.appendChild(confirmModalEl);
    
    confirmTextEl = document.getElementById("confirm-text");
    btnConfirmYesEl = document.getElementById("btn-confirm-yes");
    btnConfirmNoEl = document.getElementById("btn-confirm-no");
}

// Mascot Elements
const mascotEl = document.getElementById("mascot-container");
const bubbleEl = mascotEl.querySelector(".speech-bubble");
const mascotImgEl = document.getElementById("mascot-img");

// Global states
let activeState = "idle"; // warming, boost, night_boost, idle
let selectedScript = "warming";
let runStartTimestamp = 0;
let timerInterval = null;
let mascotMoveInterval = null;
let isMascotBusy = false;

// Update local clock in header
function updateClock() {
    const now = new Date();
    timeEl.textContent = now.toTimeString().split(" ")[0];
}
setInterval(updateClock, 1000);
updateClock();

// ========================================================
// MASCOT BEHAVIOR ENGINE
// ========================================================

const idlePhrases = [
    "Чищу кнопочки... 🧹",
    "*затяжка...* 🚬",
    "Скучно... Кофе сделать?",
    "Plitty готова к запуску! 🦾",
    "Ждем команд...",
    "Все спокойно..."
];

const runningPhrases = [
    "Работа пошла! 🚬",
    "Дымлю потихоньку...",
    "Все подключенные телефоны пашут!",
    "Ждем окончания... ⏳",
    "Кофе пьется, накрутка бьется",
    "Не трогай Plitty, пусть докрутит"
];

function showBubble(text, duration = 4000) {
    bubbleEl.textContent = text;
    bubbleEl.classList.add("visible");
    setTimeout(() => {
        bubbleEl.classList.remove("visible");
    }, duration);
}

// Set up Mascot Loop based on app status (always stationary in header next to logo)
function updateMascotLoop() {
    clearInterval(mascotMoveInterval);
    
    if (activeState === "night_boost") {
        mascotEl.className = "mascot-rage";
        mascotImgEl.src = "catgirl_bat.png";
        mascotMoveInterval = setInterval(() => {
            showBubble(runningPhrases[Math.floor(Math.random() * runningPhrases.length)]);
        }, 12000);
    } else if (activeState === "boost") {
        mascotEl.className = "mascot-gopnik";
        mascotImgEl.src = "catgirl_gopnik.png";
        showBubble("Охае епт");
        mascotMoveInterval = setInterval(() => {
            showBubble(runningPhrases[Math.floor(Math.random() * runningPhrases.length)]);
        }, 12000);
    } else {
        mascotEl.className = "mascot-sitting";
        mascotImgEl.src = "catgirl.png";
        mascotMoveInterval = setInterval(() => {
            const phrases = activeState === "idle" ? idlePhrases : runningPhrases;
            showBubble(phrases[Math.floor(Math.random() * phrases.length)]);
        }, 15000);
    }
}

// Trigger Rage/Greeting on start (instant feedback on click)
function triggerRageEmotion() {
    clearInterval(mascotMoveInterval);
    if (selectedScript === "night_boost") {
        mascotEl.className = "mascot-rage";
        mascotImgEl.src = "catgirl_bat.png";
        showBubble("Пизда вам, просмотры ебаные!");
    } else if (selectedScript === "boost") {
        mascotEl.className = "mascot-gopnik";
        mascotImgEl.src = "catgirl_gopnik.png";
        showBubble("Охае епт");
    }
}

// Initial position
setTimeout(() => {
    updateMascotLoop();
    showBubble("Привет! Plitty запущена.");
}, 1000);

// ========================================================
// UI CONTROLS & EVENT LISTENERS
// ========================================================

// Handle Script Button selection
document.querySelectorAll(".script-btn").forEach(button => {
    button.addEventListener("click", (e) => {
        if (activeState !== "idle") return; // Disable script selection when running
        
        document.querySelectorAll(".script-btn").forEach(btn => btn.classList.remove("active"));
        const btn = e.currentTarget;
        btn.classList.add("active");
        
        selectedScript = btn.getAttribute("data-script");
        
        // Show/hide accounts editor & stream options
        if (selectedScript === "warming") {
            accountsEditorGroupEl.classList.add("hidden");
            if (streamOptionsGroupEl) streamOptionsGroupEl.classList.add("hidden");
        } else if (selectedScript === "live_stream") {
            accountsEditorGroupEl.classList.add("hidden");
            if (streamOptionsGroupEl) streamOptionsGroupEl.classList.remove("hidden");
        } else {
            accountsEditorGroupEl.classList.remove("hidden");
            if (streamOptionsGroupEl) streamOptionsGroupEl.classList.add("hidden");
        }
        
        // Mascot interaction: look at selected button
        showBubble(`Скрипт: ${btn.querySelector(".btn-text").textContent}`);
    });
});

// Insert BRES list helper with Toggle logic
let isBresActive = false;

btnInsertBresEl.addEventListener("click", () => {
    isBresActive = !isBresActive;
    
    if (isBresActive) {
        targetAccountsEl.value = bresAccounts;
        btnInsertBresEl.classList.add("active");
        showBubble("BRES список включен! 📋");
    } else {
        targetAccountsEl.value = "";
        btnInsertBresEl.classList.remove("active");
        showBubble("BRES список отключен! 🗑️");
    }
});

// Reset BRES list button highlight if user manually edits textarea
targetAccountsEl.addEventListener("input", () => {
    if (targetAccountsEl.value.trim() !== bresAccounts.trim()) {
        isBresActive = false;
        btnInsertBresEl.classList.remove("active");
    }
});

const confirmPhrases = [
    "Ты уверен? Аки могут пойти по пизде!",
    "Бля, ты точно уверен? Аки же накроются пиздой!",
    "Эй, ебать, уверен? Аки забанят к хуям!",
    "Пизда акам будет, если запустишь! Точно уверен?",
    "Смотри, сука, блокнут нахуй все аки. Запускаем?",
    "Ты че, ебанулся? Аки же по пизде пойдут! Уверен?",
    "Опять накрутка? Аки пиздой накроются, бля буду. Жмем?",
    "Подумай, блядь, аки по пизде пойдут. Запускать?",
    "Ебать ты рисковый. Аки в бан улетят нахуй. Точно?",
    "Ты уверен, бля? Акам пиздец приснится!",
    "Слушай, епт, аки реально могут пиздануться. Точно жмем?",
    "Аки в говно улетят, уверен, нахуй?",
    "Бля, Лёша, акам пизда! Точно запускаем?",
    "Ты готов к пиздецу для аков? Рискуем, епт?",
    "Блядь, аки пизданет защитой! Жмем кнопку?"
];

let pendingStartAction = null;
let pendingStartAccounts = null;

function executeStartCommand(action, accounts) {
    // Trigger Rage Emotion if running boost/night boost
    if (action.includes("boost")) {
        triggerRageEmotion();
    }
    
    database.ref("command").set({
        action: action,
        accounts: accounts,
        timestamp: Date.now()
    });
}

// Action Button handler (Start / Stop)
btnActionEl.addEventListener("click", () => {
    try {
        if (activeState === "idle") {
            let action = "";
            let accounts = "";
            
            if (selectedScript === "warming") {
                action = "start_warming";
            } else if (selectedScript === "boost") {
                action = "start_boost";
                accounts = targetAccountsEl.value.trim();
                if (!accounts) {
                    alert("Пожалуйста, введите список аккаунтов!");
                    return;
                }
            } else if (selectedScript === "night_boost") {
                action = "start_night_boost";
                accounts = targetAccountsEl.value.trim();
                if (!accounts) {
                    alert("Пожалуйста, введите список аккаунтов!");
                    return;
                }
            } else if (selectedScript === "live_stream") {
                const sUser = streamerUsernameEl ? streamerUsernameEl.value.trim() : "";
                if (!sUser) {
                    alert("Пожалуйста, укажите никнейм стримера (например @dava)!");
                    return;
                }
                const likes = checkStreamLikesEl ? checkStreamLikesEl.checked : true;
                const comments = checkStreamCommentsEl ? checkStreamCommentsEl.checked : true;
                action = "start_live_stream";
                accounts = `--platform ${streamPlatform} --streamer ${sUser} --duration ${streamDuration} --mode ${streamMode}`;
                if (!likes) accounts += " --no-likes";
                if (!comments) accounts += " --no-comments";
            }
            
            if (action.includes("boost")) {
                // DOM Diagnostic logging
                try {
                    const testModal = document.getElementById("confirm-modal");
                    database.ref("dom_status").set({
                        modal_exists: !!testModal,
                        modal_classes: testModal ? testModal.className : "null",
                        modal_html: testModal ? testModal.outerHTML : "null",
                        body_children: Array.from(document.body.children).map(c => c.tagName + "#" + c.id + "." + c.className),
                        timestamp: Date.now()
                    });
                } catch (domErr) {
                    console.error("DOM logging error:", domErr);
                }

                // Show confirmation modal with random phrase
                const phrase = confirmPhrases[Math.floor(Math.random() * confirmPhrases.length)];
                confirmTextEl.textContent = phrase;
                showBubble(phrase, 5000);
                
                pendingStartAction = action;
                pendingStartAccounts = accounts;
                confirmModalEl.classList.remove("hidden");
            } else {
                executeStartCommand(action, accounts);
            }
            
        } else {
            if (confirm("Вы действительно хотите остановить выполнение сценария на всех телефонах?")) {
                database.ref("command").set({
                    action: "stop",
                    timestamp: Date.now()
                });
            }
        }
    } catch (err) {
        console.error("Action error:", err);
        try {
            database.ref("js_error").set({
                error: `Action click error: ${err.message}\nStack: ${err.stack}`,
                timestamp: Date.now()
            });
        } catch (e) {}
        alert("Ошибка интерфейса: " + err.message);
    }
});

// Confirm Modal Buttons
btnConfirmYesEl.addEventListener("click", () => {
    confirmModalEl.classList.add("hidden");
    if (pendingStartAction) {
        executeStartCommand(pendingStartAction, pendingStartAccounts);
        pendingStartAction = null;
        pendingStartAccounts = null;
    }
});

btnConfirmNoEl.addEventListener("click", () => {
    confirmModalEl.classList.add("hidden");
    pendingStartAction = null;
    pendingStartAccounts = null;
    showBubble("Запуск отменен, аки спасены. 🙌");
});

// Check Devices status button helper
const btnCheckDevicesEl = document.getElementById("btn-check-devices");
if (btnCheckDevicesEl) {
    btnCheckDevicesEl.addEventListener("click", () => {
        showBubble("Проверяем статус 31 смартфона... 📱");
        database.ref("chat/request").set({
            text: "статус",
            username: "Лёша",
            timestamp: Date.now()
        });
    });
}

// Copy Terminal Logs helper
btnCopyLogEl.addEventListener("click", () => {
    const logText = terminalContentEl.innerText;
    navigator.clipboard.writeText(logText).then(() => {
        showBubble("Логи скопированы! 💾");
    });
});

// Logs Modal Toggle Listeners
btnShowLogsEl.addEventListener("click", () => {
    logsModalEl.classList.remove("hidden");
    // Ensure logs scroll to bottom on open
    setTimeout(() => {
        terminalContentEl.scrollTop = terminalContentEl.scrollHeight;
    }, 50);
});

btnCloseLogsEl.addEventListener("click", () => {
    logsModalEl.classList.add("hidden");
});

// Setup active run UI (timer, stopwatch, etc.)
function handleTimerState(state, startTime, accountsCount) {
    if (state === "idle") {
        clearInterval(timerInterval);
        runProgressCardEl.classList.add("hidden");
        btnActionEl.textContent = "ЗАПУСТИТЬ";
        btnActionEl.className = "btn-action start-btn";
        return;
    }
    
    btnActionEl.textContent = "ОСТАНОВИТЬ";
    btnActionEl.className = "btn-action stop-btn";
    runProgressCardEl.classList.remove("hidden");
    
    runStartTimestamp = startTime;
    
    // Start local timer loop
    clearInterval(timerInterval);
    
    // Estimate total seconds
    let estimatedTotalSeconds = 660; // default for warming (11 min)
    if (state === "boost") {
        estimatedTotalSeconds = 30 + (accountsCount || 1) * 35;
    } else if (state === "night_boost") {
        const circleSecs = 30 + (accountsCount || 1) * 35;
        estimatedTotalSeconds = 5 * circleSecs + 4 * 900; // 5 circles + 4 pauses of 15m
    } else if (state === "live_stream") {
        // Длительность онлайна + 30 сек на вход + запас на рассинхрон
        estimatedTotalSeconds = (accountsCount || 5) * 60 + 30;
    }
    
    function updateProgressStats() {
        const elapsed = Math.floor((Date.now() / 1000) - runStartTimestamp);
        if (elapsed < 0) return;
        
        // Update stopwatch text
        const min = String(Math.floor(elapsed / 60)).padStart(2, "0");
        const sec = String(elapsed % 60).padStart(2, "0");
        runTimerEl.textContent = `${min}:${sec}`;
        
        // Progress percentage calculation
        let pct = Math.min(Math.floor((elapsed / estimatedTotalSeconds) * 100), 99);
        progressFillEl.style.width = `${pct}%`;
        progressPercentageEl.textContent = `${pct}%`;
        
        // ETC calculation
        const remaining = Math.max(estimatedTotalSeconds - elapsed, 0);
        const etcMin = String(Math.floor(remaining / 60)).padStart(2, "0");
        const etcSec = String(remaining % 60).padStart(2, "0");
        etcValEl.textContent = `${etcMin}:${etcSec}`;
    }
    
    updateProgressStats();
    timerInterval = setInterval(updateProgressStats, 1000);
}

// Live sync from Firebase Status
database.ref("status").on("value", (snapshot) => {
    const data = snapshot.val();
    if (!data) return;
    
    const prevState = activeState;
    activeState = data.state || "idle";
    const startTime = data.startTime || 0;
    const currentCircle = data.currentCircle || 0;
    
    // Sync active state UI
    statusBadgeEl.className = `status-badge badge-${activeState}`;
    if (activeState === "idle") {
        statusBadgeEl.textContent = "СВОБОДЕН";
        handleTimerState("idle");
    } else if (activeState === "warming") {
        statusBadgeEl.textContent = "ПРОГРЕВ";
        handleTimerState("warming", startTime);
        progressCircleEl.classList.add("hidden");
    } else if (activeState === "boost") {
        statusBadgeEl.textContent = "НАКРУТКА";
        database.ref("command/accounts").once("value").then(acctSnap => {
            const accts = acctSnap.val() || "";
            const count = accts.trim().split(/\s+/).length || 1;
            handleTimerState("boost", startTime, count);
        });
        progressCircleEl.classList.add("hidden");
    } else if (activeState === "night_boost") {
        statusBadgeEl.textContent = "НОЧЬ";
        database.ref("command/accounts").once("value").then(acctSnap => {
            const accts = acctSnap.val() || "";
            const count = accts.trim().split(/\s+/).length || 1;
            handleTimerState("night_boost", startTime, count);
        });
        progressCircleEl.classList.remove("hidden");
        circleNumEl.textContent = currentCircle;
    } else if (activeState === "live_stream") {
        statusBadgeEl.textContent = "СТРИМ 🔴";
        database.ref("command/accounts").once("value").then(acctSnap => {
            const accts = acctSnap.val() || "";
            let dur = 10;
            const durMatch = accts.match(/--duration\s+(\d+)/);
            if (durMatch) dur = parseInt(durMatch[1]);
            handleTimerState("live_stream", startTime, dur);
        });
        progressCircleEl.classList.add("hidden");
    }
    
    // If state changed, update mascot
    if (prevState !== activeState) {
        updateMascotLoop();
    }
});

// Live sync of total connected devices count from Firebase
let totalDevicesCount = 0;
let unlockedDevicesCount = 0;

function updateDevicesCountHeader() {
    if (unlockedDevicesCount > 0) {
        devicesCountEl.innerHTML = `🟢 <b>${unlockedDevicesCount}</b>/${totalDevicesCount} 📱`;
    } else {
        devicesCountEl.textContent = `${totalDevicesCount} 📱`;
    }
}

database.ref("connected_devices_count").on("value", (snapshot) => {
    totalDevicesCount = snapshot.val() || 0;
    updateDevicesCountHeader();
});

database.ref("unlocked_devices_count").on("value", (snapshot) => {
    unlockedDevicesCount = snapshot.val() || 0;
    updateDevicesCountHeader();
});

// Live sync from Firebase Active Devices
database.ref("devices").on("value", (snapshot) => {
    const devices = snapshot.val() || {};
    const devKeys = Object.keys(devices);
    
    // Update active badges
    activeDevicesBadgeEl.textContent = `${devKeys.length} активных`;
    
    if (devKeys.length === 0) {
        devicesGridEl.innerHTML = '<div class="no-devices">Нет активных устройств</div>';
        return;
    }
    
    // Render devices grid
    let html = "";
    devKeys.sort().forEach(devId => {
        const dev = devices[devId];
        const state = dev.state || "idle";
        const reps = dev.reps || 0;
        const totalReps = dev.totalReps || 0;
        
        let isUnlocked = dev.is_unlocked !== false;
        let lockTag = isUnlocked ? "🔓 Готов" : "🔒 Заблокирован";
        
        let stateText = isUnlocked ? "Ждет" : "Спит";
        if (state === "watching") stateText = "Смотрит";
        else if (state === "transitioning") stateText = "Переход";
        else if (state === "working") stateText = "Активен";
        else if (state === "staggering") stateText = "Ожидание";
        
        let stateClass = !isUnlocked ? "dev-locked" : `dev-${state}`;
        let progressText = "";
        if (state === "watching" && totalReps > 0) {
            progressText = `${reps}/${totalReps} 🔄`;
        } else if (!isUnlocked) {
            progressText = "🔒";
        }
        
        html += `
            <div class="device-item ${stateClass}">
                <span class="dev-name">${devId}</span>
                <span class="dev-status">${isUnlocked ? stateText : "🔒 Спит"}</span>
                <span class="dev-progress">${progressText}</span>
            </div>
        `;
    });
    devicesGridEl.innerHTML = html;
});

// Live sync from Firebase logs
database.ref("logs").on("value", (snapshot) => {
    const logs = snapshot.val() || [];
    
    if (logs.length === 0) {
        terminalContentEl.innerHTML = '<div class="log-line system">Лог пуст. Система готова к запуску.</div>';
        return;
    }
    
    let html = "";
    logs.forEach(line => {
        let cleanLine = line.replace(/\[\+\]/g, "").trim();
        
        let logClass = "";
        if (cleanLine.includes("успешно завершен") || cleanLine.includes("Все круги завершены") || cleanLine.includes("Success!")) {
            logClass = "success";
        } else if (cleanLine.includes("Ошибка") || cleanLine.includes("Error") || cleanLine.includes("Fail")) {
            logClass = "error";
        } else if (cleanLine.includes("===") || cleanLine.includes("Запуск")) {
            logClass = "system";
        }
        
        html += `<div class="log-line ${logClass}">${line}</div>`;
    });
    terminalContentEl.innerHTML = html;
    
    // Auto scroll to bottom
    terminalContentEl.scrollTop = terminalContentEl.scrollHeight;
});

// Guarantee fast hiding of PWA Loader
function hidePwaLoader() {
    const loader = document.getElementById("pwa-loader");
    if (loader) {
        loader.style.opacity = "0";
        loader.style.visibility = "hidden";
        setTimeout(() => { loader.style.display = "none"; }, 300);
    }
}
document.addEventListener("DOMContentLoaded", () => { setTimeout(hidePwaLoader, 500); });
window.addEventListener("load", hidePwaLoader);
setTimeout(hidePwaLoader, 1000);

// Live sync and display of last run report
let lastSeenReportTimestamp = 0;

database.ref("last_report").on("value", (snapshot) => {
    const data = snapshot.val();
    if (!data || !data.timestamp) return;
    
    // On initial load, just cache the timestamp to avoid triggering the modal immediately
    if (lastSeenReportTimestamp === 0) {
        lastSeenReportTimestamp = data.timestamp;
        return;
    }
    
    // Trigger only if the timestamp is newer (a new run finished)
    if (data.timestamp > lastSeenReportTimestamp) {
        lastSeenReportTimestamp = data.timestamp;
        showReportModal(data);
    }
});

function showReportModal(data) {
    const scriptNames = {
        "warming": "Прогрев 🔥",
        "boost": "Накрутка 📈",
        "night_boost": "Ночная накрутка 🌙",
        "live_stream": "Стрим 🎬"
    };
    reportScriptEl.textContent = scriptNames[data.scriptType] || data.scriptType;
    
    if (data.status === "completed") {
        reportStatusEl.textContent = "УСПЕШНО ЗАВЕРШЕНО ✅";
        reportStatusEl.className = "report-value status-completed";
    } else {
        reportStatusEl.textContent = "ОСТАНОВЛЕНО ПОЛЬЗОВАТЕЛЕМ ⏹️";
        reportStatusEl.className = "report-value status-stopped";
    }
    
    const min = Math.floor(data.duration / 60);
    const sec = data.duration % 60;
    reportDurationEl.textContent = `${min} мин ${sec} сек`;
    
    reportCirclesEl.textContent = data.scriptType === "live_stream" ? "Прямой эфир" : `${data.totalCircles || data.completedCircles || 1} кругов`;
    reportDevicesEl.textContent = `${data.devicesCount || data.activeDevicesCount || 0} телефонов`;
    
    // Comments metrics in report modal
    const rowComments = document.getElementById("report-row-comments");
    const valComments = document.getElementById("report-comments");
    const rowSkip = document.getElementById("report-row-skip-reason");
    const valSkip = document.getElementById("report-skip-reason");
    
    if (data.scriptType === "live_stream" || data.commentsSent !== undefined) {
        if (rowComments && valComments) {
            rowComments.style.display = "flex";
            const sent = data.commentsSent !== undefined ? data.commentsSent : 0;
            const skipped = data.commentsSkipped !== undefined ? data.commentsSkipped : 0;
            valComments.textContent = `${sent} отправлено / ${skipped} пропущено`;
        }
        if (rowSkip && valSkip) {
            if (data.commentsSkipped > 0 && data.skipReason && data.skipReason !== "Нет") {
                rowSkip.style.display = "flex";
                valSkip.textContent = data.skipReason;
            } else {
                rowSkip.style.display = "none";
            }
        }
    } else {
        if (rowComments) rowComments.style.display = "none";
        if (rowSkip) rowSkip.style.display = "none";
    }
    
    if (data.errors && data.errors.length > 0) {
        reportErrorsEl.innerHTML = data.errors.map(err => `<div>• ${err}</div>`).join("");
        reportErrorsEl.style.color = "#ff453a";
    } else {
        reportErrorsEl.textContent = "Нет";
        reportErrorsEl.style.color = "#30d158";
    }
    
    reportModalEl.classList.remove("hidden");
}

// Close report modal
btnCloseReportEl.addEventListener("click", () => {
    reportModalEl.classList.add("hidden");
});

// ========================================================
// CHATBOT INTERACTIVE INTERFACE (Plitty Persona)
// ========================================================
const chatModalEl = document.getElementById("chat-modal");
const btnOpenChat = document.getElementById("btn-open-chat");
const btnCloseChat = document.getElementById("btn-close-chat");
const chatInputEl = document.getElementById("chat-input");
const btnSendChat = document.getElementById("btn-send-chat");
const chatMessagesEl = document.getElementById("chat-messages");

let lastSentMsgTime = 0;
let currentUsername = localStorage.getItem("username") || "Лёша";
localStorage.setItem("username", currentUsername);
const FIVE_HOURS_MS = 5 * 60 * 60 * 1000; // 5 hours in ms
let chatHistory = [];

try {
    chatHistory = JSON.parse(localStorage.getItem("plitty_chat_history") || "[]");
} catch (e) {
    chatHistory = [];
}

// Close Chat
btnCloseChat.addEventListener("click", () => {
    chatModalEl.classList.add("hidden");
});

// Add message bubble
function appendChatMessage(sender, text, saveToHistory = true) {
    const bubble = document.createElement("div");
    bubble.className = `chat-message ${sender}`;
    bubble.innerHTML = text;
    chatMessagesEl.appendChild(bubble);
    chatMessagesEl.scrollTop = chatMessagesEl.scrollHeight;

    if (saveToHistory) {
        const now = Date.now();
        chatHistory.push({ sender: sender, text: text, timestamp: now });
        localStorage.setItem("plitty_chat_history", JSON.stringify(chatHistory));
        localStorage.setItem("plitty_last_chat_time", now.toString());
    }
}

// Typing Indicator
let typingBubble = null;
function showTypingIndicator() {
    if (typingBubble) return;
    typingBubble = document.createElement("div");
    typingBubble.className = "chat-message bot typing";
    typingBubble.textContent = "Печатает...";
    chatMessagesEl.appendChild(typingBubble);
    chatMessagesEl.scrollTop = chatMessagesEl.scrollHeight;
}

function removeTypingIndicator() {
    if (typingBubble) {
        typingBubble.remove();
        typingBubble = null;
    }
}

// Speech Synthesis (TTS) - disabled by user request
function speakText(text) {
    // voice playback disabled
}

// Initial Welcome message based on username presence
function renderWelcomeMessage() {
    chatMessagesEl.innerHTML = "";
    if (currentUsername) {
        database.ref("chat/username").set(currentUsername);
        appendChatMessage("bot", 
            `Опять ты, <b>${currentUsername}</b>? Я тут пиво открыть пыталась, а ты лезешь со своими командами... 🚬<br><br>` +
            `Че надо? Напиши <b>помощь</b>, если забыл команды, мне лень по сто раз объяснять.`,
            false
        );
    } else {
        appendChatMessage("bot", 
            `Че надо? 😾 Кто вообще разрешил меня будить? Я спать хочу, отвали...<br><br>` +
            `Слышь, ты кто вообще? Как звать-то тебя? Представься нормально, напиши:<br><b>Я [твое имя]</b>`,
            false
        );
    }
}

function loadChatHistory() {
    const now = Date.now();
    const lastChatTime = parseInt(localStorage.getItem("plitty_last_chat_time") || "0", 10);
    
    // Check 5-hour inactivity limit
    if (lastChatTime > 0 && (now - lastChatTime) > FIVE_HOURS_MS) {
        console.log("Inactivity > 5 hours. Clearing chat window...");
        chatHistory = [];
        localStorage.removeItem("plitty_chat_history");
        localStorage.removeItem("plitty_last_chat_time");
        chatMessagesEl.innerHTML = ""; // Empty chat window as requested
        return;
    }
    
    chatMessagesEl.innerHTML = "";
    try {
        chatHistory = JSON.parse(localStorage.getItem("plitty_chat_history") || "[]");
    } catch (e) {
        chatHistory = [];
    }
    
    if (chatHistory.length > 0) {
        chatHistory.forEach(msg => {
            const bubble = document.createElement("div");
            bubble.className = `chat-message ${msg.sender}`;
            bubble.innerHTML = msg.text;
            chatMessagesEl.appendChild(bubble);
        });
        chatMessagesEl.scrollTop = chatMessagesEl.scrollHeight;
    } else {
        renderWelcomeMessage();
    }
}

// Open Chat
btnOpenChat.addEventListener("click", () => {
    loadChatHistory();
    chatModalEl.classList.remove("hidden");
    chatMessagesEl.scrollTop = chatMessagesEl.scrollHeight;
});

// Initial load on page startup
loadChatHistory();

// Send Message
function sendUserMessage() {
    const text = chatInputEl.value.trim();
    if (!text) return;
    
    appendChatMessage("user", text);
    chatInputEl.value = "";
    
    lastSentMsgTime = Date.now();
    showTypingIndicator();
    
    // 1. If username is not set, check if user is introducing themselves
    if (!currentUsername) {
        const introMatch = text.match(/^(меня зовут|я|зови меня)\s+([a-zA-Zа-яА-ЯёЁ0-9_]+)/i);
        if (introMatch) {
            const name = introMatch[2];
            currentUsername = name;
            localStorage.setItem("username", name);
            database.ref("chat/username").set(name);
            
            setTimeout(() => {
                removeTypingIndicator();
                const reply = `Ладно, <b>${name}</b>, записала тебя в список. Но не думай, что мы теперь кореша. 😼<br><br>` +
                              `Че хотел? Можешь написать <b>помощь</b>, если хочешь узнать мои команды.`;
                appendChatMessage("bot", reply);
                speakText(reply);
            }, 1000);
        } else {
            setTimeout(() => {
                removeTypingIndicator();
                const reply = `Слышь, я не буду выполнять твои хотелки, пока ты не скажешь, кто ты! 😾<br>Напиши: <b>Я [твое имя]</b>`;
                appendChatMessage("bot", reply);
                speakText(reply);
            }, 1000);
        }
        return;
    }
    
    // Sync current username in case of multi-user
    database.ref("chat/username").set(currentUsername);
    
    // Write message to Firebase
    database.ref("chat/message").set({
        text: text,
        timestamp: lastSentMsgTime
    });
}

btnSendChat.addEventListener("click", sendUserMessage);
chatInputEl.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
        sendUserMessage();
    }
});

// Give Beer Action
document.getElementById("btn-beer-chat").addEventListener("click", () => {
    appendChatMessage("user", "<i>[Угостил Плитти пивом 🍺]</i>");
    lastSentMsgTime = Date.now();
    showTypingIndicator();
    database.ref("chat/message").set({
        text: "/give_beer",
        timestamp: lastSentMsgTime
    });
});

// Voice Mute Toggle Logic (Muted by Default)
const btnToggleVoiceEl = document.getElementById("btn-toggle-voice");
// По умолчанию озвучка ОТКЛЮЧЕНА (если пользователь явно не включил)
let isVoiceMuted = localStorage.getItem("plitty_voice_muted") !== "false";

function updateVoiceToggleButton() {
    if (btnToggleVoiceEl) {
        if (isVoiceMuted) {
            btnToggleVoiceEl.innerHTML = "🔇 Озвучка ВЫКЛ";
            btnToggleVoiceEl.style.background = "rgba(255, 45, 85, 0.18)";
            btnToggleVoiceEl.style.borderColor = "rgba(255, 45, 85, 0.35)";
            btnToggleVoiceEl.style.color = "#ff85a2";
        } else {
            btnToggleVoiceEl.innerHTML = "🔊 Озвучка ВКЛ";
            btnToggleVoiceEl.style.background = "rgba(48, 209, 88, 0.2)";
            btnToggleVoiceEl.style.borderColor = "rgba(48, 209, 88, 0.4)";
            btnToggleVoiceEl.style.color = "#30d158";
        }
    }
}

if (btnToggleVoiceEl) {
    updateVoiceToggleButton();
    btnToggleVoiceEl.addEventListener("click", () => {
        isVoiceMuted = !isVoiceMuted;
        localStorage.setItem("plitty_voice_muted", isVoiceMuted ? "true" : "false");
        updateVoiceToggleButton();
    });
}

// Listen to Bot Responses (Deduplicated with lastProcessedResponseTime)
let lastProcessedResponseTime = Date.now();

database.ref("chat/response").on("value", (snapshot) => {
    const data = snapshot.val();
    if (data && data.timestamp && data.timestamp > lastProcessedResponseTime) {
        lastProcessedResponseTime = data.timestamp;
        removeTypingIndicator();
        appendChatMessage("bot", data.text);
        
        // Воспроизводим аудио только если пользователь ЯВНО включил озвучку
        if (!isVoiceMuted && data.audio_url) {
            try {
                const audio = new Audio(data.audio_url);
                audio.play().catch(e => console.log("Audio autoplay suppressed:", e));
            } catch(e_aud) {}
        }
        
        // Handle dynamic avatar
        const avatarImg = document.querySelector("#chat-modal .modal-header img");
        if (avatarImg) {
            if (data.avatar_state === "drunk") {
                avatarImg.src = "catgirl_drunk.png";
            } else if (data.avatar_state === "normal") {
                avatarImg.src = "catgirl_avatar.png";
            }
        }
    }
});



// Stream Online Controls (Ultra Polished: TikTok, Kick, Twitch)
let streamPlatform = "tiktok";
let streamDuration = 5;
let streamMode = "organic";

const streamOptionsGroupEl = document.getElementById("stream-options-group");
const btnStreamTiktokEl = document.getElementById("btn-stream-tiktok");
const btnStreamKickEl = document.getElementById("btn-stream-kick");
const btnStreamTwitchEl = document.getElementById("btn-stream-twitch");
const streamerUsernameEl = document.getElementById("streamer-username");
const checkStreamLikesEl = document.getElementById("check-stream-likes");
const checkStreamCommentsEl = document.getElementById("check-stream-comments");
const cardStreamLikesEl = document.getElementById("card-stream-likes");

if (btnStreamTiktokEl && btnStreamKickEl) {
    btnStreamTiktokEl.addEventListener("click", () => {
        streamPlatform = "tiktok";
        btnStreamTiktokEl.className = "platform-btn active tiktok";
        btnStreamKickEl.className = "platform-btn kick";
        if (btnStreamTwitchEl) btnStreamTwitchEl.className = "platform-btn twitch";
        if (cardStreamLikesEl) cardStreamLikesEl.style.display = "flex";
        if (streamerUsernameEl) streamerUsernameEl.placeholder = "@dava или имя стримера";
    });
    btnStreamKickEl.addEventListener("click", () => {
        streamPlatform = "kick";
        btnStreamKickEl.className = "platform-btn active kick";
        btnStreamTiktokEl.className = "platform-btn tiktok";
        if (btnStreamTwitchEl) btnStreamTwitchEl.className = "platform-btn twitch";
        if (cardStreamLikesEl) cardStreamLikesEl.style.display = "none";
        if (streamerUsernameEl) streamerUsernameEl.placeholder = "n1kalin или имя канала Kick";
    });
    if (btnStreamTwitchEl) {
        btnStreamTwitchEl.addEventListener("click", () => {
            streamPlatform = "twitch";
            btnStreamTwitchEl.className = "platform-btn active twitch";
            btnStreamTiktokEl.className = "platform-btn tiktok";
            btnStreamKickEl.className = "platform-btn kick";
            if (cardStreamLikesEl) cardStreamLikesEl.style.display = "none";
            if (streamerUsernameEl) streamerUsernameEl.placeholder = "bratishkinoff или имя канала Twitch";
        });
    }
}

document.querySelectorAll(".dur-pill").forEach(pill => {
    pill.addEventListener("click", (e) => {
        document.querySelectorAll(".dur-pill").forEach(p => p.classList.remove("active"));
        const target = e.currentTarget;
        target.classList.add("active");
        streamDuration = parseInt(target.getAttribute("data-dur") || "5");
    });
});

document.querySelectorAll(".mode-pill").forEach(pill => {
    pill.addEventListener("click", (e) => {
        document.querySelectorAll(".mode-pill").forEach(p => p.classList.remove("active"));
        const target = e.currentTarget;
        target.classList.add("active");
        streamMode = target.getAttribute("data-mode") || "organic";
    });
});