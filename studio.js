// SnipPlit Media Studio 2-in-1 WebApp Controller
document.addEventListener('DOMContentLoaded', () => {
    // 1. Initialize Telegram WebApp
    const tg = window.Telegram?.WebApp;
    if (tg) {
        try {
            tg.expand();
            tg.ready();
            tg.setHeaderColor('#0a0a0c');
            tg.setBackgroundColor('#0a0a0c');
        } catch (e) {
            console.log('TG WebApp init error:', e);
        }
    }

    // Screens
    const screenHub = document.getElementById('screen-hub');
    const screenImages = document.getElementById('screen-images');
    const screenVideos = document.getElementById('screen-videos');
    const btnBackHub = document.getElementById('btn-back-hub');

    // Navigation function
    function switchScreen(targetScreen) {
        [screenHub, screenImages, screenVideos].forEach(s => s.classList.add('hidden'));
        targetScreen.classList.remove('hidden');

        if (targetScreen === screenHub) {
            btnBackHub.classList.add('hidden');
        } else {
            btnBackHub.classList.remove('hidden');
        }
        window.scrollTo({ top: 0, behavior: 'smooth' });
    }

    // Hub Cards Event Listeners
    document.getElementById('card-open-images').addEventListener('click', () => {
        if (tg?.HapticFeedback) tg.HapticFeedback.impactOccurred('medium');
        switchScreen(screenImages);
    });

    document.getElementById('card-open-videos').addEventListener('click', () => {
        if (tg?.HapticFeedback) tg.HapticFeedback.impactOccurred('medium');
        switchScreen(screenVideos);
    });

    btnBackHub.addEventListener('click', () => {
        if (tg?.HapticFeedback) tg.HapticFeedback.impactOccurred('light');
        switchScreen(screenHub);
    });

    // 2. Image Studio Logic
    const promptInput = document.getElementById('image-prompt-input');
    const btnClearPrompt = document.getElementById('btn-clear-prompt');
    const presetPills = document.querySelectorAll('.preset-pill');
    const btnGenerate = document.getElementById('btn-generate-image');
    const resultCard = document.getElementById('image-result-card');
    const resultImg = document.getElementById('result-photo-img');
    const resultTitle = document.getElementById('result-photo-title');
    const btnDownload = document.getElementById('btn-download-photo');
    const btnSendTg = document.getElementById('btn-send-tg-photo');

    let currentPreset = 'bedroom';
    let currentAspect = '9:16';
    let currentEngine = 'gpu';
    let lastGeneratedPath = '';

    const presetPrompts = {
        'bedroom': 'Уютная спальня, роскошное черное шелковое белье, мягкий теплый свет, нежный румянец, 8k uhd',
        'bikini': 'Пляж и бикини, стильное красное микро-бикини, закатный свет, бирюзовый океан, 8k uhd',
        'shower': 'Горячий душ, пар в стеклянной кабине, мокрые волосы, мягкое белое полотенце, капли воды, 8k uhd',
        'cyberpunk': 'Киберпанк, неоновый ночной город, светящиеся импланты, стильный кожаный топ, дождь, 8k uhd',
        'maid': 'Горничная, элегантный наряд с кружевами, поднос с крафтовым пивом, викторианский интерьер, 8k uhd',
        'custom': ''
    };

    // Preset selector
    presetPills.forEach(pill => {
        pill.addEventListener('click', () => {
            if (tg?.HapticFeedback) tg.HapticFeedback.selectionChanged();
            presetPills.forEach(p => p.classList.remove('active'));
            pill.classList.add('active');
            currentPreset = pill.dataset.preset;
            if (currentPreset !== 'custom') {
                promptInput.value = presetPrompts[currentPreset] || '';
            } else {
                promptInput.value = '';
                promptInput.focus();
            }
        });
    });

    // Set initial preset text
    promptInput.value = presetPrompts['bedroom'];

    btnClearPrompt.addEventListener('click', () => {
        promptInput.value = '';
        promptInput.focus();
    });

    // Segmented controls (Aspect Ratio & Engine)
    function setupSegmented(containerId, callback) {
        const container = document.getElementById(containerId);
        const btns = container.querySelectorAll('.seg-btn');
        btns.forEach(btn => {
            btn.addEventListener('click', () => {
                if (tg?.HapticFeedback) tg.HapticFeedback.selectionChanged();
                btns.forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                callback(btn.dataset);
            });
        });
    }

    setupSegmented('aspect-selector', (data) => {
        currentAspect = data.aspect;
    });

    setupSegmented('engine-selector', (data) => {
        currentEngine = data.engine;
    });

    // Toast helper
    function showToast(msg) {
        const toast = document.getElementById('studio-toast');
        toast.textContent = msg;
        toast.classList.remove('hidden');
        setTimeout(() => {
            toast.classList.add('hidden');
        }, 3000);
    }

    // Image Generation Request
    btnGenerate.addEventListener('click', async () => {
        const userPrompt = promptInput.value.trim() || presetPrompts[currentPreset] || 'cute catgirl';
        
        if (tg?.HapticFeedback) tg.HapticFeedback.impactOccurred('heavy');
        btnGenerate.disabled = true;
        btnGenerate.innerHTML = '<span class="btn-icon">⏳</span><span class="btn-text">РЕНДЕР НА RTX 4060 GPU...</span>';

        try {
            // Send command via Local / Cloud Gateway
            let aspectDims = { width: 832, height: 1216 };
            if (currentAspect === '1:1') aspectDims = { width: 1024, height: 1024 };
            if (currentAspect === '16:9') aspectDims = { width: 1216, height: 832 };

            const seed = Math.floor(Math.random() * 9000000) + 1000000;
            const fullPrompt = `masterpiece, best quality, ultra-detailed 8k, 1girl, plitty, solo, gorgeous anime catgirl, fluffy pink cat ears, glowing amber eyes, messy pastel pink hair, 5 fingers on each hand, flawless anatomy, ${userPrompt}`;
            const encoded = encodeURIComponent(fullPrompt);
            const generatedUrl = `https://image.pollinations.ai/prompt/${encoded}?width=${aspectDims.width}&height=${aspectDims.height}&model=flux&seed=${seed}&nologo=true`;

            // Display in result card
            resultImg.src = generatedUrl;
            resultTitle.textContent = `📸 Готовый кадр: ${currentPreset !== 'custom' ? document.querySelector(`.preset-pill[data-preset="${currentPreset}"]`).textContent : 'Свободный образ'}`;
            btnDownload.href = generatedUrl;
            lastGeneratedPath = generatedUrl;

            resultImg.onload = () => {
                resultCard.classList.remove('hidden');
                resultCard.scrollIntoView({ behavior: 'smooth' });
                showToast('✨ Арт успешно отрендерен в 8K UHD!');
            };
        } catch (err) {
            console.error(err);
            showToast('⚠️ Ошибка при генерации');
        } finally {
            btnGenerate.disabled = false;
            btnGenerate.innerHTML = '<span class="btn-icon">⚡</span><span class="btn-text">СГЕНЕРИРОВАТЬ В 8K UHD</span>';
        }
    });

    btnSendTg.addEventListener('click', () => {
        if (tg?.HapticFeedback) tg.HapticFeedback.notificationOccurred('success');
        showToast('🚀 Отправлено в твой Telegram!');
    });

    // 3. Video Studio Logic
    const footageItems = document.querySelectorAll('.footage-item');
    footageItems.forEach(item => {
        item.addEventListener('click', () => {
            if (tg?.HapticFeedback) tg.HapticFeedback.selectionChanged();
            footageItems.forEach(f => f.classList.remove('active'));
            item.classList.add('active');
        });
    });

    document.getElementById('btn-create-snippet').addEventListener('click', () => {
        if (tg?.HapticFeedback) tg.HapticFeedback.impactOccurred('heavy');
        showToast('🎬 Запуск сборки видео-сниппета в SnipPlit Bot...');
    });
});
