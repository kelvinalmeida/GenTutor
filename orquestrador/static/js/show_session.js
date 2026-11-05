document.addEventListener("DOMContentLoaded", () => {
    let countdownInterval = null;
    let taticaAtiva = false;
    let adaptiveTacticEnabled = false;

    let debateSicrono_isActive = false;
    let apresentacaoSicrona_isActive = false;
    let reuso_isActive = false;
    let envio_informacao_isActive = false;
    let regras_isActive = false;
    let current_tatic_description = 'Nenhuma tática ativa no momento.';
    let activeTacticIndex = null;
    let reusoExercisesState = null; // null=desconhecido, true=tem exercícios, false=sem exercícios
    let _proactiveTimer = null;
    let _proactiveShown = false;

    const session_id = window.session_id;
    const token = window.token;
    const domain_id = window.domain_id;
    const my_username = window.my_username;
    const my_id = window.my_id;


    // Verificar se o usuário tem notas extras, se não tiver, exibir mensagem
    let student_extra_note = document.getElementById("student-extra-note-card-created");
    if (!student_extra_note) {
        const noteCard = document.getElementById("student-extra-note-card");
        if (noteCard) noteCard.innerHTML = '<em>Sem notas extras atribuidas.</em>';
    }

    // Verificar se o usuário tem respostas de exercícios, se não tiver, exibir mensagem
    let student_answers_card = document.getElementById("student-answers-card-created");
    if (!student_answers_card) {
        const answersCard = document.getElementById("student-answers-card");
        if (answersCard) answersCard.innerHTML = '<em>Sem respostas de exercícios enviadas nesta sessão.</em>';
    }

    // Variável para armazenar a instância atual da UI do Chat
    let currentChatUI = null;

    console.log("Session ID: ", session_id);

    taticDescription("Sessão finalizada ou sem tática ativa no momento.");
    function taticDescription(description) {
        if (description === 'hidden' || description === undefined || description.trim() === "") {
            description = "Nenhuma descrição disponível";
        }
        const descriptionElement = document.getElementById("current_tatic_description");
        if (descriptionElement) descriptionElement.innerText = description;
    }


    function qual_tatica_esta_ativa(debate_sicrono, apresentacao_sincrona, reuso, envio_informacao, regras) {
        debateSicrono_isActive = debate_sicrono;
        apresentacaoSicrona_isActive = apresentacao_sincrona;
        reuso_isActive = reuso;
        envio_informacao_isActive = envio_informacao;
        regras_isActive = regras;
        // console.log("Tática Ativa: ", debateSicrono, apresentacaoSicrona, reuso);
    }


    function debateSicrono(id_chat, targetContainerId = "tatic_here") {
        fetch(`/chat_fragment/${id_chat}/${session_id}`)
            .then(response => response.text())
            .then(html => {
                const chatHere = document.createElement("div");
                chatHere.innerHTML = html;
                chatHere.id = "debate_sicrono";

                // Reexecutar scripts
                const scripts = Array.from(chatHere.querySelectorAll("script"));
                let loadedScripts = 0;
                const totalScripts = scripts.filter(s => s.src).length;

                scripts.forEach(oldScript => {
                    const newScript = document.createElement("script");

                    if (oldScript.src) {
                        newScript.src = oldScript.src;
                        newScript.onload = () => {
                            loadedScripts++;
                            if (loadedScripts === totalScripts && typeof initializeChatComponent === "function") {
                                if (currentChatUI) currentChatUI.destroy();
                                currentChatUI = initializeChatComponent();
                            }
                        };
                        document.body.appendChild(newScript);
                    } else {
                        newScript.textContent = oldScript.textContent;
                        document.body.appendChild(newScript);
                    }
                });

                if (totalScripts === 0 && typeof initializeChatComponent === "function") {
                    if (currentChatUI) currentChatUI.destroy();
                    currentChatUI = initializeChatComponent();
                }

                const chatContainer = document.getElementById(targetContainerId);
                chatContainer.innerHTML = "";
                chatContainer.appendChild(chatHere);
            });
    }


    function showAdaptiveReasoning(reasoning) {
        const banner = document.getElementById("adaptive-reasoning-banner");
        const text = document.getElementById("adaptive-reasoning-text");
        if (banner && text && reasoning) {
            text.textContent = reasoning;
            banner.classList.remove("d-none");
        }
    }

    function hideAdaptiveReasoning() {
        const banner = document.getElementById("adaptive-reasoning-banner");
        if (banner) banner.classList.add("d-none");
    }

    function showSessionGoal(goalText) {
        const banner = document.getElementById("session-goal-banner");
        const text = document.getElementById("session-goal-text");
        if (banner && text && goalText) {
            text.textContent = goalText;
            banner.classList.remove("d-none");
            localStorage.setItem(`session_goal_${session_id}_${my_id}`, goalText);
        }
    }

    function restoreSessionGoal() {
        const stored = localStorage.getItem(`session_goal_${session_id}_${my_id}`);
        if (stored) showSessionGoal(stored);
    }

    function showAdaptiveLoadingState() {
        clearInterval(countdownInterval);
        const timerEl = document.getElementById("tacticTimer");
        if (timerEl) timerEl.innerText = "...";
        const nameEl = document.getElementById("tacticName");
        if (nameEl) nameEl.innerText = "Personalizando...";
        const tacticArea = document.getElementById("tatic_here");
        if (tacticArea) {
            tacticArea.innerHTML = `
                <div class="text-center py-5">
                    <div class="spinner-border text-primary" style="width:3rem;height:3rem;" role="status">
                        <span class="visually-hidden">Carregando...</span>
                    </div>
                    <p class="mt-3 fw-bold text-primary">🧠 A IA está personalizando seu ensino...</p>
                    <p class="text-muted small">Analisando seu perfil e desempenho para escolher a melhor próxima atividade.</p>
                </div>`;
        }
        hideAdaptiveReasoning();
    }

    function randomDelay(maxMs) {
        return new Promise(resolve => setTimeout(resolve, Math.random() * maxMs));
    }

    function _clearProactiveTimer() {
        if (_proactiveTimer) { clearTimeout(_proactiveTimer); _proactiveTimer = null; }
        _proactiveShown = false;
        const existing = document.getElementById('proactive-card');
        if (existing) existing.remove();
    }

    function _startProactiveTimer() {
        _clearProactiveTimer();
        _proactiveTimer = setTimeout(() => {
            if (_proactiveShown) return;
            _proactiveShown = true;

            const pdfContainer = document.getElementById('pdf_container');
            if (!pdfContainer) return;

            const card = document.createElement('div');
            card.id = 'proactive-card';
            card.className = 'card border-primary shadow-sm mb-3';
            card.innerHTML = `
                <div class="card-header bg-primary text-white fw-bold d-flex justify-content-between align-items-center">
                    <span>🤖 Posso te ajudar?</span>
                    <button type="button" class="btn-close btn-close-white btn-sm" id="proactive-dismiss"></button>
                </div>
                <div class="card-body">
                    <p class="mb-2">Notei que você está estudando este material há alguns minutos. Está conseguindo entender o conteúdo?</p>
                    <p class="text-muted small mb-3">💡 Lembre-se: o PDF estará disponível para download ao final da sessão.</p>
                    <div class="d-flex gap-2 flex-wrap">
                        <button class="btn btn-outline-primary btn-sm" id="proactive-ok">✅ Estou entendendo bem</button>
                        <button class="btn btn-primary btn-sm" id="proactive-generate">📝 Gerar outro exemplo</button>
                    </div>
                    <div id="proactive-feedback" class="mt-2"></div>
                </div>`;

            const pdfTab = document.getElementById('pdf-tab');
            if (pdfTab) new bootstrap.Tab(pdfTab).show();
            pdfContainer.insertBefore(card, pdfContainer.firstChild);

            document.getElementById('proactive-dismiss').onclick = () => {
                card.remove();
                _startProactiveTimer();
            };

            document.getElementById('proactive-ok').onclick = () => {
                card.remove();
                _startProactiveTimer();
            };

            document.getElementById('proactive-generate').onclick = () => {
                const feedbackEl = document.getElementById('proactive-feedback');
                const okBtn = document.getElementById('proactive-ok');
                const genBtn = document.getElementById('proactive-generate');
                if (feedbackEl) feedbackEl.innerHTML = `
                    <span class="spinner-border spinner-border-sm text-primary me-2" role="status"></span>
                    <span class="text-muted small">Gerando exemplo personalizado...</span>`;
                if (okBtn) okBtn.disabled = true;
                if (genBtn) genBtn.disabled = true;

                fetch('/orchestrator/agent/generate_wrong_answers_text', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ student_id: my_id, session_id: session_id, attempt_number: 0 })
                })
                .then(r => r.json())
                .then(aiData => {
                    card.remove();
                    if (!aiData.study_text) return;
                    localStorage.setItem(`reuso_study_text_${session_id}_${my_id}`, aiData.study_text);
                    const newCard = document.createElement('div');
                    newCard.className = 'card border-primary shadow-sm mb-3';
                    newCard.innerHTML = `
                        <div class="card-header bg-primary text-white fw-bold">📚 Exemplo Personalizado</div>
                        <div class="card-body">
                            <p class="text-muted small mb-3">Gerado especialmente para você com base no conteúdo desta sessão.</p>
                            <div style="white-space: pre-wrap; line-height: 1.8;">${aiData.study_text}</div>
                        </div>`;
                    pdfContainer.innerHTML = '';
                    pdfContainer.appendChild(newCard);
                })
                .catch(() => { card.remove(); });
            };
        }, 7 * 60 * 1000);
    }

    function renderPlanPanel(tacticSequence, strategyTactics, currentTacticIndex) {
        const panel = document.getElementById('plan-panel');
        if (!panel || !tacticSequence || !tacticSequence.length || !strategyTactics) return;

        const currentPos = tacticSequence.indexOf(currentTacticIndex);

        const items = tacticSequence.map((idx, pos) => {
            const tactic = strategyTactics[idx];
            if (!tactic) return '';
            const name = tactic.name || `Tática ${idx + 1}`;
            let icon, textClass, bgClass, strikeClass;
            if (pos < currentPos) {
                icon = '✅'; textClass = 'text-muted'; bgClass = ''; strikeClass = 'text-decoration-line-through';
            } else if (idx === currentTacticIndex) {
                icon = '▶️'; textClass = 'fw-bold text-primary'; bgClass = 'list-group-item-primary'; strikeClass = '';
            } else {
                icon = '⏳'; textClass = 'text-secondary'; bgClass = ''; strikeClass = '';
            }
            return `<li class="list-group-item d-flex align-items-center gap-2 py-2 ${bgClass}">
                <span style="font-size:0.95rem">${icon}</span>
                <span class="${textClass} ${strikeClass} small">${pos + 1}. ${name}</span>
            </li>`;
        }).join('');

        panel.innerHTML = `
            <div class="card shadow-sm" style="border-left: 4px solid #667eea; overflow: hidden;">
                <div class="card-header py-2 px-3 fw-semibold small"
                    style="background: linear-gradient(135deg,#667eea15,#764ba215);">
                    📋 Plano personalizado desta sessão
                </div>
                <ul class="list-group list-group-flush">${items}</ul>
            </div>`;
        panel.classList.remove('d-none');
    }

    function advanceStudentTactic() {
        if (adaptiveTacticEnabled) {
            const hasPlan = !!localStorage.getItem(`plan_sequence_${session_id}_${my_id}`);
            if (hasPlan) {
                const tacticArea = document.getElementById("tatic_here");
                if (tacticArea) {
                    tacticArea.innerHTML = `
                        <div class="text-center py-4">
                            <div class="spinner-border text-primary" style="width:2rem;height:2rem;" role="status">
                                <span class="visually-hidden">Carregando...</span>
                            </div>
                            <p class="mt-2 text-muted small">Carregando próxima atividade…</p>
                        </div>`;
                }
            } else {
                showAdaptiveLoadingState();
            }
            const delay = hasPlan ? Promise.resolve() : randomDelay(3000);
            return delay
            .then(() => fetch('/orchestrator/agent/adaptive_next_tactic', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ student_id: my_id, session_id: session_id })
            }))
            .then(r => r.json())
            .then(aiData => {
                if (aiData.reasoning) {
                    localStorage.setItem(`adaptive_reasoning_${session_id}_${my_id}`, aiData.reasoning);
                }
                if (aiData.next_tactic_name === 'Sessão Concluída') {
                    fetch('/orchestrator/agent/save_session_memory', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ student_id: my_id, session_id: session_id })
                    }).catch(() => {});
                }
                activeTacticIndex = null;
                fetchCurrentTactic(session_id);
            })
            .catch(() => { activeTacticIndex = null; fetchCurrentTactic(session_id); });
        } else {
            return fetch(`/sessions/${session_id}/student_advance_tactic`, { method: 'POST' })
                .then(() => { activeTacticIndex = null; fetchCurrentTactic(session_id); })
                .catch(() => fetchCurrentTactic(session_id));
        }
    }

    function startCountdown(remainingTime, strategyTactics, tacticName, tacticDomainId) {
        clearInterval(countdownInterval);
        // Limpa qualquer estado de loading (spinner da IA) antes de montar a nova tática
        const tacticHereEl = document.getElementById("tatic_here");
        if (tacticHereEl) tacticHereEl.innerHTML = '';

        // Reuso: se o tempo já expirou ao recarregar a página, garante pelo menos
        // 1 tick no branch "else" para que a UI de abas seja construída antes de parar.
        let timeLeft = (remainingTime <= 0 && tacticName === "Reuso") ? 1 : remainingTime;

        // Resetar estado de ativação a cada nova tática
        taticaAtiva = false;

        debateSicrono_isActive = false;
        apresentacaoSicrona_isActive = false;
        reuso_isActive = false;
        envio_informacao_isActive = false;
        regras_isActive = false;
        reusoExercisesState = null;
        _clearProactiveTimer();

        // Remove os elementos da tática anterior antes de montar a nova
        removerElemento();

        const _tickFn = () => {
            // Evitar auto-avanço se for a tática de "Regra", pois ela tem lógica própria de execução
            const isRegra = (tacticName === "Regra" || tacticName === "Regras");

            if (timeLeft <= 0 && !isRegra) {
                clearInterval(countdownInterval);
                const timerEl = document.getElementById("tacticTimer");
                if (timerEl) timerEl.innerText = "Concluído";

                const isReuso = (tacticName === "Reuso");
                if (isReuso && (reusoExercisesState === null || reusoExercisesState === true)) {
                    // Reuso com exercícios: aguarda o aluno completar e passar nos exercícios
                    return;
                }

                // Avança automaticamente para a próxima tática
                advanceStudentTactic();
            } else {
                let minutes = Math.floor(timeLeft / 60);
                let seconds = timeLeft % 60;
                let formattedTime = `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
                const timerEl2 = document.getElementById("tacticTimer");
                if (timerEl2) timerEl2.innerText = formattedTime;

                timeLeft--;

                // const elementToRemove = document.getElementById('chat');
                // if (elementToRemove) {
                //     elementToRemove.remove(); // Remove o próprio elemento
                // }

                // Verifica se a tática atual é "Debate Sincrono"
                if (tacticName == "Debate Sincrono") {

                    // Evitar adicionar o botão várias vezes:
                    if (!document.getElementById("debate_sicrono")) {

                        // (debate_sicrono, apresentacao_sincrona, reuso, envio_informacao, regras)
                        qual_tatica_esta_ativa(true, false, false, false, false);

                        removerElemento();

                        id_chat = null;
                        for (let tatic_stra in strategyTactics) {
                            // console.log(strategyTactics[tatic_stra].name);
                            if (strategyTactics[tatic_stra].name == "Debate Sincrono") {
                                id_chat = strategyTactics[tatic_stra].chat_id;
                                break;
                            }
                        }

                        if (taticaAtiva == false) {
                            console.log("Entrando no debate sincrono");
                            debateSicrono(id_chat);
                            taticaAtiva = true;
                        }
                    }
                }
                else if (tacticName == "Apresentacao Sincrona") {
                    if (!document.getElementById("apresentacao_sincrona")) {

                        // (debate_sicrono, apresentacao_sincrona, reuso, envio_informacao, regras)
                        qual_tatica_esta_ativa(false, true, false, false, false);
                        removerElemento();

                        let button = document.createElement("button");
                        button.innerHTML = `
            <span style="font-size: 1.5rem; font-weight: bold;">
                🎥 Entrar na Apresentação Síncrona
            </span>
        `;
                        button.id = "apresentacao_sincrona";

                        // Adicionando múltiplas classes do Bootstrap para destaque visual
                        button.className = "btn btn-warning shadow-lg border-3 border-dark mt-4 py-4 px-5 fs-4 rounded-pill";

                        link_do_meet = null;

                        for (let tatic_stra in strategyTactics) {
                            if (strategyTactics[tatic_stra].name == "Apresentacao Sincrona") {
                                link_do_meet = strategyTactics[tatic_stra].description;
                                break;
                            }
                        }

                        button.onclick = function () {
                            window.open(link_do_meet, "_blank");
                        };

                        let tatic_here = document.getElementById("tatic_here");
                        tatic_here.appendChild(button);
                    }
                }

                else if (tacticName == "Reuso") {
                    if (!document.getElementById("reuso_tabs")) {

                        qual_tatica_esta_ativa(false, false, true, false, false);
                        removerElemento();

                        const tatic_here = document.getElementById("tatic_here");

                        // Criar container das abas
                        const tabContainer = document.createElement("div");
                        tabContainer.id = "reuso_tabs";

                        tabContainer.innerHTML = `
            <ul class="nav nav-tabs" id="reusoTab" role="tablist">
                <li class="nav-item" role="presentation">
                    <button class="nav-link active" id="pdf-tab" data-bs-toggle="tab" data-bs-target="#pdfs" type="button" role="tab">PDFs</button>
                </li>
                <li class="nav-item" role="presentation">
                    <button class="nav-link" id="ex-tab" data-bs-toggle="tab" data-bs-target="#exercicios" type="button" role="tab">Exercícios</button>
                </li>
                <li class="nav-item" role="presentation">
                    <button class="nav-link" id="vid-tab" data-bs-toggle="tab" data-bs-target="#videos" type="button" role="tab">Vídeos</button>
                </li>
            </ul>
            <div class="tab-content mt-3">
                <div class="tab-pane fade show active" id="pdfs" role="tabpanel">
                    <div id="pdf_container"></div>
                </div>
                <div class="tab-pane fade" id="exercicios" role="tabpanel">
                    <div id="exercise_container" class="p-2">Carregando exercícios...</div>
                </div>
                <div class="tab-pane fade" id="videos" role="tabpanel">
                    <div id="video_container" class="p-2">Carregando vídeos...</div>
                </div>
            </div>
        `;


                        // Forçar o funcionamento das abas Bootstrap depois de adicionar dinamicamente
                        const tabTriggerList = tabContainer.querySelectorAll('button[data-bs-toggle="tab"]');
                        tabTriggerList.forEach(function (tabEl) {
                            tabEl.addEventListener('click', function (event) {
                                const tab = new bootstrap.Tab(tabEl);
                                tab.show();
                            });
                        });


                        tatic_here.appendChild(tabContainer);
                        _startProactiveTimer();

                        const _reusoDomainId = tacticDomainId || domain_id;

                        // ---------- Carregar PDFs ----------
                        const pdfContainer = document.getElementById("pdf_container");
                        const _studyTextKey = `reuso_study_text_${session_id}_${my_id}`;
                        const _savedStudyText = localStorage.getItem(_studyTextKey);

                        if (_savedStudyText) {
                            // Restaura o texto gerado pela IA em tentativa anterior
                            const _card = document.createElement('div');
                            _card.className = 'card border-warning shadow-sm mb-3';
                            const _cardHeader = document.createElement('div');
                            _cardHeader.className = 'card-header bg-warning text-dark fw-bold';
                            _cardHeader.textContent = 'Material de Revisão Personalizado';
                            const _cardBody = document.createElement('div');
                            _cardBody.className = 'card-body';
                            const _hint = document.createElement('p');
                            _hint.className = 'text-muted small mb-3';
                            _hint.textContent = 'Leia este material antes de tentar novamente.';
                            const _textDiv = document.createElement('div');
                            _textDiv.style.cssText = 'white-space: pre-wrap; line-height: 1.8;';
                            _textDiv.textContent = _savedStudyText;
                            _cardBody.appendChild(_hint);
                            _cardBody.appendChild(_textDiv);
                            _card.appendChild(_cardHeader);
                            _card.appendChild(_cardBody);
                            pdfContainer.innerHTML = '';
                            pdfContainer.appendChild(_card);
                        } else {
                            const _loadPdfs = (pdfs) => {
                                pdfs.forEach(pdf => {
                                    fetch(`/pdfs/${pdf.id}`, {
                                        headers: { "Authorization": `Bearer ${token}` }
                                    })
                                    .then(response => {
                                        if (!response.ok) throw new Error("Erro ao baixar PDF");
                                        return response.blob();
                                    })
                                    .then(blob => {
                                        const url = URL.createObjectURL(blob);
                                        const embed = document.createElement("embed");
                                        embed.src = url;
                                        embed.type = "application/pdf";
                                        embed.width = "100%";
                                        embed.height = "600px";
                                        embed.className = "mb-3";
                                        pdfContainer.appendChild(embed);
                                    })
                                    .catch(error => console.error("Erro ao carregar PDF: ", error));
                                });
                            };

                            if (tacticDomainId) {
                                fetch(`/domains/${_reusoDomainId}/pdfs`, {
                                    headers: { "Authorization": `Bearer ${token}` }
                                })
                                .then(r => r.json())
                                .then(pdfs => _loadPdfs(pdfs))
                                .catch(() => {});
                            } else {
                                const pdfDataEl = document.getElementById("pdf_data");
                                if (pdfDataEl) {
                                    _loadPdfs(JSON.parse(pdfDataEl.getAttribute("data-pdfs")));
                                }
                            }
                        }

                        // ----------Carregar Exercícios----------
                        if (!_reusoDomainId) {
                            reusoExercisesState = false;
                            const container = document.getElementById("exercise_container");
                            if (container) container.innerHTML = "<p class='text-muted'>Nenhum domínio configurado para esta tática.</p>";
                        } else {
                        fetch(`/domains/${_reusoDomainId}/exercises`, {
                            headers: {
                                "Authorization": `Bearer ${token}`
                            }
                        })
                            .then(res => res.json())
                            .then(data => {
                                reusoExercisesState = data.length > 0;
                                const container = document.getElementById("exercise_container");

                                if (!Array.isArray(data) || data.length === 0) {
                                    container.innerHTML = "<p class='text-muted'>Nenhum exercício encontrado neste domínio.</p>";
                                    return;
                                }

                                // Cria o formulário principal
                                const form = document.createElement("form");
                                form.id = "exerciseForm";

                                // Cabeçalho com contador de progresso
                                const progressBar = document.createElement("div");
                                progressBar.className = "d-flex justify-content-between align-items-center mb-4 p-3 rounded-3";
                                progressBar.style.cssText = "background:linear-gradient(135deg,#667eea18,#764ba218);border:1px solid #667eea30;";
                                progressBar.innerHTML = `
                                    <div class="d-flex align-items-center gap-2">
                                        <span style="font-size:1.3rem;">📝</span>
                                        <span class="fw-semibold text-secondary">${data.length} ${data.length === 1 ? 'questão' : 'questões'}</span>
                                    </div>
                                    <span id="progress-count" class="badge rounded-pill fs-6 px-3 py-2" style="background:#667eea;">0 / ${data.length}</span>
                                `;
                                form.appendChild(progressBar);

                                // Letras das alternativas
                                const _letters = 'ABCDE';

                                // Para cada exercício, cria um card estilizado
                                data.forEach((ex, index) => {
                                    const card = document.createElement("div");
                                    card.className = "mb-4";
                                    card.innerHTML = `
                                        <div class="card border-0 shadow-sm overflow-hidden">
                                            <div class="card-header d-flex align-items-start gap-3 py-3 border-0"
                                                 style="background:linear-gradient(135deg,#667eea18,#764ba218); border-left:4px solid #667eea !important;">
                                                <span class="badge rounded-circle fw-bold flex-shrink-0 d-flex align-items-center justify-content-center"
                                                      style="width:34px;height:34px;font-size:0.95rem;background:#667eea;margin-top:1px;">
                                                    ${index + 1}
                                                </span>
                                                <span class="fw-semibold lh-sm pt-1">${ex.question}</span>
                                            </div>
                                            <div class="card-body pt-3 pb-2 px-3">
                                                ${ex.options.map((opt, i) => `
                                                    <label class="d-flex align-items-center gap-3 p-3 mb-2 rounded-3 border _opt-lbl"
                                                           style="cursor:pointer;transition:background .15s,border-color .15s;border-color:#dee2e6!important;">
                                                        <input type="radio" name="exercise_${ex.id}" value="${i}" required class="d-none">
                                                        <span class="_opt-letter fw-bold flex-shrink-0 rounded-circle d-flex align-items-center justify-content-center"
                                                              style="width:32px;height:32px;background:#f0f0f0;color:#555;font-size:.85rem;transition:background .15s,color .15s;">
                                                            ${_letters[i] || i + 1}
                                                        </span>
                                                        <span class="flex-grow-1">${opt}</span>
                                                    </label>
                                                `).join("")}
                                            </div>
                                        </div>
                                    `;
                                    form.appendChild(card);
                                });

                                // Listener de mudança: destaca opção selecionada + atualiza progresso
                                form.addEventListener("change", e => {
                                    if (e.target.type !== "radio") return;
                                    // Remove destaque das opções do mesmo grupo
                                    form.querySelectorAll(`input[name="${e.target.name}"]`).forEach(r => {
                                        const lbl = r.closest("._opt-lbl");
                                        if (lbl) {
                                            lbl.style.background = "";
                                            lbl.style.borderColor = "#dee2e6";
                                            const letter = lbl.querySelector("._opt-letter");
                                            if (letter) { letter.style.background = "#f0f0f0"; letter.style.color = "#555"; }
                                        }
                                    });
                                    // Destaca a selecionada
                                    const selLbl = e.target.closest("._opt-lbl");
                                    if (selLbl) {
                                        selLbl.style.background = "rgba(102,126,234,.1)";
                                        selLbl.style.borderColor = "#667eea";
                                        const selLetter = selLbl.querySelector("._opt-letter");
                                        if (selLetter) { selLetter.style.background = "#667eea"; selLetter.style.color = "white"; }
                                    }
                                    // Atualiza contador de progresso
                                    const answered = new Set();
                                    form.querySelectorAll("input[type='radio']:checked").forEach(r => answered.add(r.name));
                                    const countEl = document.getElementById("progress-count");
                                    if (countEl) {
                                        countEl.textContent = `${answered.size} / ${data.length}`;
                                        countEl.style.background = answered.size === data.length ? "#198754" : "#667eea";
                                    }
                                });

                                // Botão de envio e feedback
                                const submitArea = document.createElement("div");
                                submitArea.innerHTML = `
                                    <div class="d-grid mt-2">
                                        <button type="submit" class="btn btn-lg fw-bold py-3"
                                                style="background:linear-gradient(135deg,#667eea,#764ba2);color:white;border:none;">
                                            📤 Enviar Respostas
                                        </button>
                                    </div>
                                    <div id="formFeedback" class="mt-3 text-center fw-bold"></div>
                                `;
                                form.appendChild(submitArea);

                                container.innerHTML = ""; // Limpa qualquer conteúdo anterior
                                container.appendChild(form); // Insere o formulário

                                // Restaura countdown do botão se ainda estiver ativo após reload
                                const _cooldownKey = `reuso_cooldown_end_${session_id}_${my_id}`;
                                const _cooldownEnd = parseInt(localStorage.getItem(_cooldownKey) || '0');
                                if (_cooldownEnd > Date.now()) {
                                    const _restoreBtn = form.querySelector('button[type="submit"]');
                                    if (_restoreBtn) {
                                        _restoreBtn.disabled = true;
                                        let _secsLeft = Math.ceil((_cooldownEnd - Date.now()) / 1000);
                                        const _updateRestoreBtn = () => {
                                            const m = Math.floor(_secsLeft / 60);
                                            const s = _secsLeft % 60;
                                            _restoreBtn.textContent = `Aguarde ${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')} para tentar novamente`;
                                        };
                                        _updateRestoreBtn();
                                        const _restoreTimer = setInterval(() => {
                                            _secsLeft--;
                                            if (_secsLeft <= 0) {
                                                clearInterval(_restoreTimer);
                                                _restoreBtn.disabled = false;
                                                _restoreBtn.textContent = 'Enviar respostas';
                                                localStorage.removeItem(_cooldownKey);
                                            } else {
                                                _updateRestoreBtn();
                                            }
                                        }, 1000);
                                    }
                                }

                                // Adiciona o event listener de envio DEPOIS de inserir no DOM
                                form.addEventListener("submit", function (e) {
                                    e.preventDefault();

                                    const studentName = my_username;
                                    const studentId = my_id;

                                    if (!studentName || !studentId) {
                                        document.getElementById("formFeedback").textContent = "Preencha nome e ID do aluno.";
                                        return;
                                    }

                                    const formData = new FormData(e.target);
                                    const answers = [];

                                    for (const [key, value] of formData.entries()) {
                                        if (key.startsWith("exercise_")) {
                                            const exerciseId = key.split("_")[1];
                                            answers.push({
                                                exercise_id: parseInt(exerciseId),
                                                answer: parseInt(value)
                                            });
                                        }
                                    }

                                    const totalQuestions = data.length; // Cada objeto em `data` é uma pergunta
                                    if (answers.length !== totalQuestions) {
                                        document.getElementById("formFeedback").textContent = "Responda todas as questões antes de enviar.";
                                        return;
                                    }


                                    const submitBtn = form.querySelector('button[type="submit"]');
                                    if (submitBtn) submitBtn.disabled = true;

                                    fetch("/sessions/submit_answer", {
                                        method: "POST",
                                        headers: {
                                            "Content-Type": "application/json",
                                            "Authorization": `Bearer ${token}`
                                        },
                                        body: JSON.stringify({
                                            student_id: studentId,
                                            student_name: studentName,
                                            answers: answers,
                                            session_id: session_id,
                                        })
                                    })
                                        .then(function (response) {
                                            if (!response.ok) {
                                                throw new Error("Erro ao enviar respostas");
                                            }
                                            return response.json();
                                        })
                                        .then(function(respData) {
                                            const feedbackEl = document.getElementById("formFeedback");
                                            feedbackEl.textContent = respData.resp;
                                            console.log("Respostas enviadas:", respData);
                                            _clearProactiveTimer();

                                            if (respData.passed) {
                                                feedbackEl.className = "mt-2 text-success fw-bold";
                                                // Limpa dados persistidos ao passar nos exercícios
                                                localStorage.removeItem(`reuso_cooldown_end_${session_id}_${my_id}`);
                                                localStorage.removeItem(`reuso_study_text_${session_id}_${my_id}`);
                                                localStorage.removeItem(`reuso_attempt_${session_id}_${my_id}_${activeTacticIndex || 0}`);
                                                if (adaptiveTacticEnabled) {
                                                    const _hasPlan = !!localStorage.getItem(`plan_sequence_${session_id}_${my_id}`);
                                                    const _completedIdx = activeTacticIndex;

                                                    const _doReusoTransition = (planReady) => {
                                                        if (planReady) {
                                                            const _area = document.getElementById("tatic_here");
                                                            if (_area) {
                                                                _area.innerHTML = `<div class="text-center py-4">
                                                                    <div class="spinner-border text-primary" style="width:2rem;height:2rem;" role="status"><span class="visually-hidden">Carregando...</span></div>
                                                                    <p class="mt-2 text-muted small">Carregando próxima atividade…</p>
                                                                </div>`;
                                                            }
                                                        }
                                                        const _delay = planReady ? Promise.resolve() : randomDelay(3000);
                                                        _delay
                                                        .then(() => fetch('/orchestrator/agent/adaptive_next_tactic', {
                                                            method: 'POST',
                                                            headers: { 'Content-Type': 'application/json' },
                                                            body: JSON.stringify({ student_id: my_id, session_id: session_id, completed_tactic_index: _completedIdx })
                                                        }))
                                                        .then(r => r.json())
                                                        .then(aiData => {
                                                            if (aiData.reasoning) {
                                                                localStorage.setItem(`adaptive_reasoning_${session_id}_${my_id}`, aiData.reasoning);
                                                            }
                                                            if (aiData.next_tactic_name === 'Sessão Concluída') {
                                                                fetch('/orchestrator/agent/save_session_memory', {
                                                                    method: 'POST',
                                                                    headers: { 'Content-Type': 'application/json' },
                                                                    body: JSON.stringify({ student_id: my_id, session_id: session_id })
                                                                }).catch(() => {});
                                                            }
                                                            activeTacticIndex = null;
                                                            setTimeout(() => fetchCurrentTactic(session_id), 500);
                                                        })
                                                        .catch(() => { activeTacticIndex = null; setTimeout(() => fetchCurrentTactic(session_id), 1500); });
                                                    };

                                                    if (!_hasPlan) {
                                                        // Reuso concluído: planeja as táticas restantes com as notas reais
                                                        showAdaptiveLoadingState();
                                                        fetch('/orchestrator/agent/replan_session', {
                                                            method: 'POST',
                                                            headers: { 'Content-Type': 'application/json' },
                                                            body: JSON.stringify({ student_id: my_id, session_id: session_id, is_replan: false, completed_tactic_index: _completedIdx })
                                                        })
                                                        .then(r => r.json())
                                                        .then(planData => {
                                                            if (planData.overall_goal) showSessionGoal(planData.overall_goal);
                                                            if (planData.new_sequence) {
                                                                localStorage.setItem(`plan_sequence_${session_id}_${my_id}`, JSON.stringify(planData.new_sequence));
                                                            }
                                                            _doReusoTransition(true);
                                                        })
                                                        .catch(() => _doReusoTransition(false));
                                                    } else {
                                                        _doReusoTransition(true);
                                                    }
                                                } else {
                                                    setTimeout(() => fetchCurrentTactic(session_id), 1500);
                                                }
                                            } else {
                                                feedbackEl.className = "mt-2 text-danger fw-bold";

                                                // --- Desabilita o botão por 3 minutos com countdown ---
                                                if (submitBtn) {
                                                    submitBtn.disabled = true;
                                                    const cooldownEndTime = Date.now() + 180 * 1000;
                                                    localStorage.setItem(`reuso_cooldown_end_${session_id}_${my_id}`, cooldownEndTime.toString());
                                                    let secondsLeft = 180;
                                                    const updateBtn = () => {
                                                        const mins = Math.floor(secondsLeft / 60);
                                                        const secs = secondsLeft % 60;
                                                        submitBtn.textContent = `Aguarde ${String(mins).padStart(2,'0')}:${String(secs).padStart(2,'0')} para tentar novamente`;
                                                    };
                                                    updateBtn();
                                                    const btnCountdown = setInterval(() => {
                                                        secondsLeft--;
                                                        if (secondsLeft <= 0) {
                                                            clearInterval(btnCountdown);
                                                            submitBtn.disabled = false;
                                                            submitBtn.textContent = 'Enviar respostas';
                                                            localStorage.removeItem(`reuso_cooldown_end_${session_id}_${my_id}`);
                                                        } else {
                                                            updateBtn();
                                                        }
                                                    }, 1000);
                                                }

                                                // --- Modal informativo ---
                                                const existingModal = document.getElementById('wrongAnswersModal');
                                                if (existingModal) existingModal.remove();

                                                const modalEl = document.createElement('div');
                                                modalEl.id = 'wrongAnswersModal';
                                                modalEl.className = 'modal fade';
                                                modalEl.setAttribute('tabindex', '-1');
                                                modalEl.innerHTML = `
                                                    <div class="modal-dialog modal-dialog-centered">
                                                        <div class="modal-content border-warning">
                                                            <div class="modal-header bg-warning text-dark">
                                                                <h5 class="modal-title fw-bold">Resultado dos Exercícios</h5>
                                                                <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                                                            </div>
                                                            <div class="modal-body">
                                                                <p class="fw-semibold">${feedbackEl.textContent}</p>
                                                                <hr>
                                                                <p id="modal-ai-status" class="mb-0">
                                                                    <span class="spinner-border spinner-border-sm text-warning me-2" role="status"></span>
                                                                    Gerando material de revisão personalizado com foco nos seus erros...
                                                                </p>
                                                            </div>
                                                            <div class="modal-footer">
                                                                <button type="button" class="btn btn-warning" data-bs-dismiss="modal">Fechar e Revisar</button>
                                                            </div>
                                                        </div>
                                                    </div>
                                                `;
                                                document.body.appendChild(modalEl);
                                                const bsModal = new bootstrap.Modal(modalEl);
                                                bsModal.show();

                                                // --- Spinner na aba PDF ---
                                                const pdfContainer = document.getElementById("pdf_container");
                                                if (pdfContainer) {
                                                    pdfContainer.innerHTML = `
                                                        <div class="text-center p-4">
                                                            <div class="spinner-border text-warning" role="status"></div>
                                                            <p class="mt-2 text-muted">Gerando material de revisão personalizado...</p>
                                                        </div>
                                                    `;
                                                    const pdfTabBtn = document.getElementById("pdf-tab");
                                                    if (pdfTabBtn) new bootstrap.Tab(pdfTabBtn).show();
                                                }

                                                // Rastreia o número de tentativas para variar a abordagem pedagógica
                                                const _attemptKey = `reuso_attempt_${session_id}_${studentId}_${activeTacticIndex || 0}`;
                                                const _attemptNumber = parseInt(localStorage.getItem(_attemptKey) || '0') + 1;
                                                localStorage.setItem(_attemptKey, _attemptNumber.toString());

                                                // Na 2ª falha, replaneja o restante da sessão em background
                                                if (_attemptNumber === 2 && adaptiveTacticEnabled) {
                                                    fetch('/orchestrator/agent/replan_session', {
                                                        method: 'POST',
                                                        headers: { 'Content-Type': 'application/json' },
                                                        body: JSON.stringify({ student_id: my_id, session_id: session_id, executed_tactic_indices: [] })
                                                    })
                                                    .then(r => r.json())
                                                    .then(replanData => {
                                                        if (replanData.overall_goal) showSessionGoal(replanData.overall_goal);
                                                        if (replanData.new_sequence) {
                                                            localStorage.setItem(`plan_sequence_${session_id}_${my_id}`, JSON.stringify(replanData.new_sequence));
                                                        }
                                                    })
                                                    .catch(() => {});
                                                }

                                                fetch('/orchestrator/agent/generate_wrong_answers_text', {
                                                    method: 'POST',
                                                    headers: { 'Content-Type': 'application/json' },
                                                    body: JSON.stringify({ student_id: studentId, session_id: session_id, attempt_number: _attemptNumber })
                                                })
                                                .then(r => r.json())
                                                .then(aiData => {
                                                    // Persiste o texto gerado para sobreviver a reloads
                                                    if (aiData.study_text) {
                                                        localStorage.setItem(`reuso_study_text_${session_id}_${my_id}`, aiData.study_text);
                                                    }

                                                    // Atualiza o modal com confirmação
                                                    const modalStatus = document.getElementById('modal-ai-status');
                                                    if (modalStatus) {
                                                        modalStatus.innerHTML = `
                                                            <span class="text-success fw-bold">Material gerado com sucesso!</span>
                                                            Acesse a aba <strong>PDFs</strong> para ler o conteúdo personalizado focado nas suas dificuldades.
                                                        `;
                                                    }

                                                    if (pdfContainer) {
                                                        const card = document.createElement('div');
                                                        card.className = 'card border-warning shadow-sm mb-3';

                                                        const cardHeader = document.createElement('div');
                                                        cardHeader.className = 'card-header bg-warning text-dark fw-bold';
                                                        cardHeader.textContent = 'Material de Revisão Personalizado';

                                                        const cardBody = document.createElement('div');
                                                        cardBody.className = 'card-body';

                                                        const hint = document.createElement('p');
                                                        hint.className = 'text-muted small mb-3';
                                                        hint.textContent = 'Leia este material antes de tentar novamente.';

                                                        const textDiv = document.createElement('div');
                                                        textDiv.style.cssText = 'white-space: pre-wrap; line-height: 1.8;';
                                                        textDiv.textContent = aiData.study_text || 'Não foi possível gerar o material. Tente novamente.';

                                                        cardBody.appendChild(hint);
                                                        cardBody.appendChild(textDiv);
                                                        card.appendChild(cardHeader);
                                                        card.appendChild(cardBody);
                                                        pdfContainer.innerHTML = '';
                                                        pdfContainer.appendChild(card);
                                                    }
                                                    form.reset();
                                                })
                                                .catch(() => {
                                                    const modalStatus = document.getElementById('modal-ai-status');
                                                    if (modalStatus) {
                                                        modalStatus.textContent = 'Não foi possível gerar o material automaticamente. Revise o conteúdo e tente novamente.';
                                                    }
                                                    form.reset();
                                                });
                                            }
                                        })
                                        .catch(function(err) {
                                            console.error("Erro ao enviar respostas:", err);
                                            const feedbackEl = document.getElementById("formFeedback");
                                            feedbackEl.textContent = "Erro ao enviar respostas. Tente novamente.";
                                            feedbackEl.className = "mt-2 text-danger";
                                            if (submitBtn) submitBtn.disabled = false;
                                        });
                                });
                            })
                            .catch(err => {
                                console.error("Erro ao carregar exercícios:", err);
                                reusoExercisesState = false;
                            });
                        } // end exercises fetch block


                        // ---------- Carregar Vídeos ----------
                        fetch(`/domains/${_reusoDomainId}/videos`, {
                            headers: {
                                "Authorization": `Bearer ${token}`
                            }
                        })
                            .then(res => res.json())
                            // .then(res => console.log(res))
                            .then(videos_json => {
                                const container = document.getElementById("video_container");
                                container.innerHTML = "";

                                // console.log("videos_json: ", videos_json)

                                videos_json.videos_youtube.forEach(video => {
                                    const embedUrl = convertToEmbedUrl(video.url);
                                    const div = document.createElement("div");
                                    div.className = "mb-3";
                                    div.innerHTML = `<iframe width="560" height="315" 
                                        src="${embedUrl}" 
                                        title="YouTube video player" 
                                        frameborder="0" 
                                        allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" 
                                        allowfullscreen></iframe>`;
                                    container.appendChild(div);
                                });

                                videos_json.videos_uploaded.forEach(video => {
                                    const videoTag = document.createElement("video");
                                    const div = document.createElement("div");
                                    videoTag.controls = true;
                                    videoTag.src = `/video/uploaded/${video.id}`;
                                    videoTag.className = "w-100";
                                    div.appendChild(videoTag);
                                    container.appendChild(div);
                                });
                            })
                            .catch(err => {
                                console.error("Erro ao carregar vídeos:", err);
                            });

                    }
                }


                else if (tacticName == "Envio de Informacao") {
                    if (!document.getElementById("envio_informacao_aviso")) {

                        // (debate_sicrono, apresentacao_sincrona, reuso, envio_informacao, regras)
                        qual_tatica_esta_ativa(false, false, false, true, false);
                        removerElemento();

                        // Criar container visual com mensagem e botão
                        const avisoDiv = document.createElement("div");
                        avisoDiv.id = "envio_informacao_aviso";
                        avisoDiv.className = "alert alert-info shadow-lg p-4 rounded border border-primary";

                        avisoDiv.innerHTML = `
            <h4 class="mb-3 text-primary">
                📬 Verifique seu e-mail!
            </h4>
            <p class="lead mb-4">
                Acabamos de enviar um material importante para o e-mail cadastrado.
                Por favor, confira sua caixa de entrada!
            </p>
            <button class="btn btn-success btn-lg px-4 py-2 rounded-pill fw-bold" id="btn_ver_email_gmail">
                Ir para o Gmail ✉️
            </button>
            <button class="btn btn-success btn-lg px-4 py-2 rounded-pill fw-bold" id="btn_ver_email_outlook">
                Ir para o Outlook ✉️
            </button>
        `;

                        // Adicionar ação ao botão
                        avisoDiv.querySelector("#btn_ver_email_gmail").onclick = function () {
                            window.open("https://mail.google.com/", "_blank");
                        };

                        avisoDiv.querySelector("#btn_ver_email_outlook").onclick = function () {
                            window.open("https://outlook.live.com/", "_blank");
                        };

                        let tatic_here = document.getElementById("tatic_here");
                        tatic_here.appendChild(avisoDiv);
                    }
                }

                // --------------------------------------------------------
                // NOVA LÓGICA: TÁTICA DE REGRA (Agente Decisor)
                // --------------------------------------------------------
                else if (tacticName == "Regra" || tacticName == "Regras") {
                    // Evita executar múltiplas vezes se já estiver "ativo" ou processando
                    if (!document.getElementById("regra_processing")) {

                        // (debate_sicrono, apresentacao_sincrona, reuso, envio_informacao, regras)
                        qual_tatica_esta_ativa(false, false, false, false, true);
                        removerElemento();

                        const tatic_here = document.getElementById("tatic_here");

                        // Card visual de processamento
                        const processingDiv = document.createElement("div");
                        processingDiv.id = "regra_processing";
                        processingDiv.className = "card shadow border-primary mb-3 text-center p-4";
                        processingDiv.innerHTML = `
                            <div class="card-body">
                                <h3 class="card-title text-primary mb-3">
                                    <i class="bi bi-cpu-fill"></i> Agente de Estratégia
                                </h3>
                                <p class="card-text lead">
                                    Analisando o desempenho da turma e o conteúdo para decidir o próximo passo...
                                </p>
                                <div class="spinner-border text-primary mt-3" role="status" style="width: 3rem; height: 3rem;">
                                    <span class="visually-hidden">Loading...</span>
                                </div>
                                <p class="mt-2 text-muted"><small>Isso pode levar alguns segundos.</small></p>
                            </div>
                        `;
                        tatic_here.appendChild(processingDiv);

                        // --- Chamada ao Backend ---
                        console.log("Iniciando execução da Tática de Regras...");
                        fetch(`/sessions/${session_id}/execute_rules`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ student_id: my_id })
                        })
                        .then(response => {
                            if (!response.ok) throw new Error("Erro na execução da regra");
                            return response.json();
                        })
                        .then(data => {
                            console.log("Decisão do Agente de Regras:", data);

                            // Atualiza a UI com a decisão
                            processingDiv.innerHTML = `
                                <div class="card-body">
                                    <h3 class="card-title text-success mb-3">
                                        <i class="bi bi-check-circle-fill"></i> Decisão Tomada!
                                    </h3>
                                    <p class="card-text lead">
                                        <strong>Ação:</strong> ${data.decision === 'REPEAT_TACTIC' ? 'Reforço de Conteúdo (Repetir Tática)' : 'Avançar Estratégia'}
                                    </p>
                                    <div class="alert alert-secondary text-start" role="alert">
                                        <strong><i class="bi bi-lightbulb"></i> Motivo:</strong> ${data.reasoning}
                                    </div>
                                    <p class="mt-3 text-muted">Redirecionando...</p>
                                </div>
                            `;

                            // Pequeno delay para leitura antes de recarregar
                            setTimeout(() => {
                                location.reload();
                            }, 4000);
                        })
                        .catch(err => {
                            console.error("Falha na regra:", err);
                            processingDiv.innerHTML = `
                                <div class="alert alert-danger">
                                    Ocorreu um erro ao processar a regra. Avançando automaticamente...
                                </div>
                            `;
                            // Fallback: Avança forçado após erro
                            setTimeout(() => {
                                fetch(`/sessions/${session_id}/next_tactic`, { method: 'POST' })
                                .then(() => location.reload());
                            }, 3000);
                        });
                    }
                }
            }

        };
        if (timeLeft > 0) _tickFn(); // Build tactic UI immediately — no 1-second delay on first render
        countdownInterval = setInterval(_tickFn, 1000);
    }

    function convertToEmbedUrl(url) {
        try {
            const parsedUrl = new URL(url);
            const videoId = parsedUrl.searchParams.get("v");
            if (videoId) {
                return `https://www.youtube.com/embed/${videoId}`;
            }
            return url; // fallback: se não tiver parâmetro "v"
        } catch (e) {
            console.error("URL inválida:", url);
            return url;
        }
    }


    function removerElemento() {
        let reusoTabs = document.getElementById("reuso_tabs");
        if (reusoTabs && !reuso_isActive) {
            reusoTabs.remove();
        }

        let apresentacao_sincrona = document.getElementById("apresentacao_sincrona");
        if (apresentacao_sincrona && !apresentacaoSicrona_isActive) {
            apresentacao_sincrona.remove();
        }

        let chatElement = document.getElementById("debate_sicrono");
        if (!debateSicrono_isActive) {
             if (chatElement) {
                 chatElement.remove();
             }

             // Limpeza correta da UI usando o método destroy() da classe
             if (currentChatUI) {
                 console.log("Limpando instância da UI do Chat...");
                 currentChatUI.destroy();
                 currentChatUI = null;
             }

             // O Service (socket) pode permanecer conectado ou ser desconectado aqui
             // Se quisermos desconectar totalmente ao sair da aba:
             // if (window.ChatService && window.ChatService.instance) {
             //    window.ChatService.instance.disconnect();
             // }
        }

        let envio_informacao_aviso = document.getElementById("envio_informacao_aviso");
        if (envio_informacao_aviso && !envio_informacao_isActive) {
            envio_informacao_aviso.remove();
        }

        let regraProcessing = document.getElementById("regra_processing");
        if (regraProcessing && !regras_isActive) {
            regraProcessing.remove();
        }
    }

    function realod_page() {
        console.log("Recarregando a página...");
        location.reload();
    }

    function showStudentStartArea() {
        const startArea = document.getElementById("student-start-area");
        const tacticArea = document.getElementById("student-tactic-area");
        if (startArea) startArea.style.display = '';
        if (tacticArea) tacticArea.style.display = 'none';
    }

    function showStudentTacticArea() {
        const startArea = document.getElementById("student-start-area");
        const tacticArea = document.getElementById("student-tactic-area");
        if (startArea) startArea.style.display = 'none';
        if (tacticArea) tacticArea.style.display = '';
    }

    function fetchCurrentTactic(session_id) {
        const studentParam = my_id ? `?student_id=${my_id}` : '';
        fetch(`/sessions/${session_id}/current_tactic${studentParam}`)
            .then(response => response.json())
            .then(data => {
                console.log("Dados da tática atual: ", data);

                adaptiveTacticEnabled = data.adaptive_tactic_enabled || false;

                if (data.strategy_id && window.current_strategy_id && data.strategy_id != window.current_strategy_id) {
                    console.log("Strategy changed, reloading page...");
                    location.reload();
                    return;
                }

                if (data.session_status === 'not_started') {
                    // Sessão iniciada/reiniciada pelo professor: limpa material e timer do Reuso
                    localStorage.removeItem(`reuso_study_text_${session_id}_${my_id}`);
                    localStorage.removeItem(`reuso_cooldown_end_${session_id}_${my_id}`);
                    localStorage.removeItem(`adaptive_reasoning_${session_id}_${my_id}`);
                    localStorage.removeItem(`session_goal_${session_id}_${my_id}`);
                    localStorage.removeItem(`plan_sequence_${session_id}_${my_id}`);
                    hideAdaptiveReasoning();
                    const goalBanner = document.getElementById("session-goal-banner");
                    if (goalBanner) goalBanner.classList.add("d-none");
                    const planPanelEl = document.getElementById('plan-panel');
                    if (planPanelEl) { planPanelEl.innerHTML = ''; planPanelEl.classList.add('d-none'); }
                    activeTacticIndex = null;
                    showStudentStartArea();
                    const btn = document.getElementById("studentStartBtn");
                    if (btn) {
                        btn.disabled = false;
                        btn.innerHTML = '<i class="bi bi-play-circle-fill me-2"></i> Iniciar Minha Sessão';
                    }
                    const msg = document.getElementById("student-start-msg");
                    if (msg) msg.innerText = "Clique para iniciar o seu percurso de aprendizagem.";
                    return;
                }

                if (data.session_status === 'aguardando') {
                    showStudentStartArea();
                    const btn = document.getElementById("studentStartBtn");
                    if (btn) {
                        btn.disabled = true;
                        btn.innerHTML = '<i class="bi bi-hourglass me-2"></i> Aguardando professor abrir a sessão…';
                    }
                    return;
                }

                if (data.tactic && data.session_status === 'in-progress') {
                    showStudentTacticArea();

                    // Restaura objetivo da sessão ao recarregar
                    if (adaptiveTacticEnabled) restoreSessionGoal();

                    // Renderiza painel do plano se existir
                    if (adaptiveTacticEnabled) {
                        const _storedSeq = localStorage.getItem(`plan_sequence_${session_id}_${my_id}`);
                        if (_storedSeq) {
                            try { renderPlanPanel(JSON.parse(_storedSeq), data.strategy_tactics, data.current_tactic_index); } catch(e) {}
                        }
                    }

                    const nameEl = document.getElementById("tacticName");
                    if (nameEl) nameEl.innerText = data.tactic.name;
                    taticDescription(data.tactic.description || "Nenhuma descrição disponível");
                    if (data.current_tactic_index !== activeTacticIndex) {
                        activeTacticIndex = data.current_tactic_index;

                        // Exibe o raciocínio da IA se existir no localStorage
                        if (adaptiveTacticEnabled) {
                            const storedReasoning = localStorage.getItem(`adaptive_reasoning_${session_id}_${my_id}`);
                            if (storedReasoning) {
                                showAdaptiveReasoning(storedReasoning);
                                localStorage.removeItem(`adaptive_reasoning_${session_id}_${my_id}`);
                            } else {
                                hideAdaptiveReasoning();
                            }
                        } else {
                            hideAdaptiveReasoning();
                        }

                        const tacticNameLower = data.tactic.name.trim().toLowerCase();
                        const isMudancaEstrategia =
                            tacticNameLower.includes('mudança de estratégia') ||
                            tacticNameLower.includes('mudanca de estrategia') ||
                            tacticNameLower.includes('mudança de estrategia') ||
                            tacticNameLower.includes('mudanca de estratégia');

                        if (isMudancaEstrategia) {
                            clearInterval(countdownInterval);
                            const timerEl = document.getElementById("tacticTimer");
                            if (timerEl) timerEl.innerText = "...";
                            taticDescription("Mudando de estratégia, aguarde...");
                            const description = data.tactic.description || '';
                            const matchId = description.match(/\d+/);
                            if (matchId) {
                                const newStrategyId = parseInt(matchId[0]);
                                fetch(`/sessions/${session_id}/student_change_strategy`, {
                                    method: 'POST',
                                    headers: { 'Content-Type': 'application/json' },
                                    body: JSON.stringify({ strategy_id: newStrategyId })
                                })
                                .then(() => { activeTacticIndex = null; setTimeout(() => location.reload(), 1000); })
                                .catch(() => {
                                    activeTacticIndex = null;
                                    fetch(`/sessions/${session_id}/student_advance_tactic`, { method: 'POST' })
                                        .then(() => fetchCurrentTactic(session_id))
                                        .catch(() => fetchCurrentTactic(session_id));
                                });
                            } else {
                                activeTacticIndex = null;
                                fetch(`/sessions/${session_id}/student_advance_tactic`, { method: 'POST' })
                                    .then(() => fetchCurrentTactic(session_id))
                                    .catch(() => fetchCurrentTactic(session_id));
                            }
                        } else {
                            startCountdown(data.remaining_time, data.strategy_tactics, data.tactic.name, data.tactic.domain_id);
                        }
                    }
                } else if (data.session_status === 'student_finished') {
                    activeTacticIndex = null;
                    clearInterval(countdownInterval);
                    qual_tatica_esta_ativa(false, false, false, false, false);
                    removerElemento();
                    showStudentStartArea();
                    const btn = document.getElementById("studentStartBtn");
                    if (btn) {
                        btn.disabled = true;
                        btn.innerHTML = '<i class="bi bi-check-circle-fill me-2"></i> Sessão concluída! Aguardando o professor reiniciar...';
                    }
                    const msg = document.getElementById("student-start-msg");
                    if (msg) msg.innerText = "Parabéns! Você completou todas as táticas. O professor poderá reiniciar a sessão.";
                } else {
                    activeTacticIndex = null;
                    const nameEl = document.getElementById("tacticName");
                    const timerEl = document.getElementById("tacticTimer");
                    if (nameEl) nameEl.innerText = "Sessão finalizada";
                    if (timerEl) timerEl.innerText = "--";
                    qual_tatica_esta_ativa(false, false, false, false, false);
                    removerElemento();
                    taticDescription("Sessão finalizada ou sem tática ativa no momento.");
                    clearInterval(countdownInterval);
                }
            })
            .catch(error => {
                console.error("Erro ao buscar tática atual:", error.message);
                const nameEl = document.getElementById("tacticName");
                const timerEl = document.getElementById("tacticTimer");
                if (nameEl) nameEl.innerText = "Erro ao carregar";
                if (timerEl) timerEl.innerText = "--";
            });
    }


    // ===== PROFESSOR =====
    const startSessionBtn = document.getElementById("startSessionBtn");
    if (startSessionBtn) {
        startSessionBtn.addEventListener("click", () => {
            fetch(`/sessions/start/${session_id}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ use_agent: false })
            }).then(response => {
                if (response.ok) {
                    location.reload();
                } else {
                    alert("Sessão já iniciada ou erro ao iniciar.");
                }
            });
        });
    }

    const endSessionBtn = document.getElementById("endSessionBtn");
    if (endSessionBtn) {
        endSessionBtn.addEventListener("click", () => {
            if (confirm("Tem certeza que deseja encerrar a sessão?")) {
                endSessionBtn.disabled = true;
                endSessionBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Encerrando...';
                fetch(`/sessions/end/${session_id}`)
                    .then(response => {
                        if (response.ok) {
                            endSessionBtn.innerHTML = '<i class="bi bi-stop-circle me-2"></i>Sessão Encerrada';
                            const startBtn = document.getElementById("startSessionBtn");
                            if (startBtn) startBtn.classList.remove("d-none");
                            const statusPill = document.querySelector('.status-in-progress');
                            if (statusPill) {
                                statusPill.className = 'status-pill status-finished';
                                statusPill.innerHTML = '<i class="bi bi-check-circle-fill" style="font-size:0.7rem;"></i> Encerrada';
                            }
                        } else {
                            endSessionBtn.disabled = false;
                            endSessionBtn.innerHTML = '<i class="bi bi-stop-circle me-2"></i>Encerrar Sessão';
                            alert("Erro ao encerrar a sessão.");
                        }
                    })
                    .catch(() => {
                        endSessionBtn.disabled = false;
                        endSessionBtn.innerHTML = '<i class="bi bi-stop-circle me-2"></i>Encerrar Sessão';
                        alert("Erro ao tentar encerrar a sessão.");
                    });
            }
        });
    }

    if (window.user_type === 'teacher') {
        if (window.teacher_debate_chat_id !== null && window.teacher_debate_chat_id !== undefined) {
            const debateSection = document.getElementById("teacher-debate-section");
            if (debateSection) debateSection.classList.remove("d-none");
            debateSicrono(window.teacher_debate_chat_id, "teacher_debate_chat");
        }
        if (window.teacher_apresentacao_link) {
            const apresentacaoSection = document.getElementById("teacher-apresentacao-section");
            if (apresentacaoSection) apresentacaoSection.classList.remove("d-none");
        }
    }

    // ===== ALUNO =====
    const studentStartBtn = document.getElementById("studentStartBtn");
    if (studentStartBtn) {
        studentStartBtn.addEventListener("click", () => {
            studentStartBtn.disabled = true;
            fetch(`/sessions/${session_id}/student_start`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${token}`
                }
            }).then(response => {
                if (response.ok) {
                    showStudentTacticArea();
                    fetchCurrentTactic(session_id);
                } else {
                    studentStartBtn.disabled = false;
                    alert("Erro ao iniciar a sessão. Tente novamente.");
                }
            }).catch(() => {
                studentStartBtn.disabled = false;
                alert("Erro ao iniciar a sessão. Tente novamente.");
            });
        });
    }

    if (window.user_type === 'student') {
        fetchCurrentTactic(session_id);
        setInterval(() => fetchCurrentTactic(session_id), 5000);
    }

    const adaptiveTacticSwitch = document.getElementById("adaptiveTacticSwitch");
    if (adaptiveTacticSwitch) {
        adaptiveTacticSwitch.addEventListener("change", function () {
            const enabled = this.checked;
            fetch(`/sessions/${session_id}/set_adaptive_tactic`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ enabled: enabled })
            })
            .then(r => {
                if (r.ok) {
                    adaptiveTacticEnabled = enabled;
                    const statusEl = document.getElementById("adaptive-tactic-status");
                    if (statusEl) {
                        statusEl.textContent = enabled
                            ? "Ativado: a IA escolhe a próxima tática para cada aluno."
                            : "Desativado: alunos seguem a ordem normal das táticas.";
                    }
                } else {
                    console.error("Erro ao atualizar tática adaptativa:", r.status);
                    adaptiveTacticSwitch.checked = !enabled;
                }
            })
            .catch(err => {
                console.error("Erro ao atualizar tática adaptativa:", err);
                adaptiveTacticSwitch.checked = !enabled;
            });
        });
    }
});
