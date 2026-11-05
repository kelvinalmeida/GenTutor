import os
import json
import logging
from flask import Blueprint, request, jsonify, current_app
from config import Config
from openai import OpenAI
# from google import genai
# from google.genai import types

logging.basicConfig(level=logging.INFO)

agente_strategies_bp = Blueprint('agente_strategies_bp', __name__)

# Configuração da API Key
# Tenta pegar do ambiente (Docker env), ou usa a chave direta como fallback
# GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")


# Tenta importar a conexão do banco
try:
    from db import create_connection
except ImportError:
    from ...db import create_connection


@agente_strategies_bp.route('/agent/critique', methods=['POST'])
def critique_strategy():
    """
    Agente Worker: Crítico Pedagógico
    """
    try:
        # 1. Extração de dados
        data = request.json
        strategy_name = data.get('name')
        tactics_list = data.get('tactics', [])

        # 2. Construção do Prompt
        tactics_str = ', '.join(tactics_list) if tactics_list else 'Nenhuma tática informada'
        prompt = f"""Avalie se a estratégia de ensino abaixo é pedagogicamente coerente.

TÁTICAS DO SISTEMA:
- Reuso: apresenta recursos didáticos (vídeos, PDFs, exercícios) por tempo determinado. Deve ser a primeira tática.
- Debate Síncrono: interação em tempo real via chat entre alunos e professor.
- Envio de Informação: envia materiais educativos por e-mail aos alunos.
- Mudança de Estratégia: troca a abordagem didática durante a sessão.
- Regras: dispara ações condicionais baseadas no desempenho do aluno.

ESTRATÉGIA SUBMETIDA:
Nome: {strategy_name}
Sequência: {tactics_str}

Critérios: começa com Reuso, varia abordagens, faz sentido pedagógico.

{{"grade": <inteiro 0-10>, "feedback": "<2-3 frases justificando a nota>"}}"""
        
        # --- 4. Chamada LLM ---
        client = OpenAI(
            api_key=Config.GROQ_API_KEY,
            base_url="https://api.groq.com/openai/v1"
        )
        
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "Responda apenas JSON."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.2 
        )

        content_text = response.choices[0].message.content
        ai_response = json.loads(content_text)

        # 4. Chamada ao Modelo
        # Usando response_mime_type para forçar JSON (funcionalidade do Gemini 1.5+)
        # response = client.models.generate_content(
        #     model="gemini-2.5-flash-lite-preview-09-2025", 
        #     contents=prompt,
        #     config=types.GenerateContentConfig(
        #         response_mime_type="application/json"
        #     )
        # ) 

        # logging.info(f"****************Resposta do Agente Gemini: {response.text}")

        # # 5. Tratamento da Resposta
        # # A nova SDK retorna o texto limpo, e como pedimos JSON, podemos fazer o parse direto
        # ai_response = json.loads(response.text)
        
        final_score = ai_response.get('grade', 0)
        final_feedback = ai_response.get('feedback', 'Sem feedback gerado.')
        status = "approved" if final_score >= 7 else "needs_revision"

        return jsonify({
            "grade": final_score,
            "feedback": final_feedback,
            "status": status
        })

    except Exception as e:
        logging.error(f"Erro no Agente Gemini: {str(e)}")
        return jsonify({
            "grade": 0, 
            "feedback": f"Erro interno na IA: {str(e)}",
            "status": "error"
        }), 500
    


@agente_strategies_bp.route('/agent/decide_next_tactic', methods=['POST'])
def decide_next_tactic():
    """
    Agente de Estratégia: Recebe o contexto e o histórico.
    Agora traduz os IDs do histórico para NOMES antes de enviar ao LLM.
    """
    data = request.get_json()

    # --- 1. Extração do Contexto ---
    strategy_id = data.get('strategy_id') # estrategia da sessão para consultar táticas disponíveis
    executed_ids = data.get('executed_tactics', []) # Ex: [1, 2], IDs das tatocas já feitos na sessão
    
    student_profile_summary = data.get('student_profile_summary', 'Perfil não informado.')
    performance_summary = data.get('performance_summary', 'Sem dados de performance.')
    
    domain_name = data.get('domain_name', 'Tópico Geral')
    domain_description = data.get('domain_description', '')
    article_text = data.get('article_text', '')

    if not strategy_id:
        return jsonify({"error": "strategy_id é obrigatório"}), 400

    conn = None
    try:
        db_url = current_app.config.get("SQLALCHEMY_DATABASE_URI") or os.getenv("DATABASE_URL")
        conn = create_connection(db_url)
        
        if not conn:
            return jsonify({"error": "Falha na conexão com o banco"}), 500

        with conn.cursor() as cur:
            # --- 2. Busca Táticas DISPONÍVEIS (Opções) ---
            cur.execute("""
                SELECT id, name, description, time 
                FROM tactics 
                WHERE strategy_id = %s
            """, (int(strategy_id),))
            available_rows = cur.fetchall()

            available_tactics = []
            for row in available_rows:
                # Normalização de acesso (Dict ou Tupla)
                if isinstance(row, dict):
                    t = row
                else:
                    t = {'id': row[0], 'name': row[1], 'description': row[2], 'time': row[3]}
                
                available_tactics.append(t)

            # --- 3. Busca Nomes das Táticas JÁ EXECUTADAS (Histórico) ---
            # O Gemini precisa saber que o ID 1 é "Vídeo" para não repetir "Vídeo"
            executed_names_list = []

            logging.info(f"Táticas executadas (IDs): {executed_ids}")
            
            if executed_ids:
                # Query para pegar nomes baseados nos IDs recebidos
                cur.execute("""
                    SELECT id, name 
                    FROM tactics 
                    WHERE id = ANY(%s)
                """, (executed_ids,))
                history_rows = cur.fetchall()
                
                for h_row in history_rows:
                    if isinstance(h_row, dict):
                        h_id, h_name = h_row['id'], h_row['name']
                    else:
                        h_id, h_name = h_row[0], h_row[1]
                    
                    executed_names_list.append(f"{h_name} (ID {h_id})")

        if not available_tactics:
            return jsonify({"error": "Nenhuma tática encontrada para esta estratégia"}), 404

        # --- 4. Construção do Prompt ---
        
        # Lista de disponíveis para escolha
        tactics_joined = "\n".join([
            f"- ID {t['id']}: {t['name']} (Tempo: {t['time']} min) | Desc: {t['description']}"
            for t in available_tactics
        ])

        # Lista de histórico formatada com NOMES
        if executed_names_list:
            history_text = ", ".join(executed_names_list)
            history_instruction = f"Táticas já realizadas: [{history_text}]. EVITE repetir o mesmo tipo de tática."
        else:
            history_instruction = "Nenhuma tática executada ainda (Início da sessão)."

        prompt = f"""
        Você é um Arquiteto Pedagógico (Agente de Estratégia).
        Escolha a PRÓXIMA ação de ensino baseada no perfil e histórico.

        === Como as taticas funcionam ===
        - Tática de Reuso: Apresenta recursos didáticos de um domínio, como definições e exemplos, por um tempo estipulado.

        - Tática de Debate Síncrono: Realiza interações em tempo real via chat entre alunos e professores por um período determinado.

        - Tática de Envio de Informação: Envia materiais e conteúdos educativos para os e-mails dos alunos de forma direta.

        - Tática de Mudança de Estratégia: Possibilita a troca da estratégia didática atual por uma nova abordagem durante a sessão.

        - Tática de Regras: Define ações que são disparadas apenas quando condições específicas de seleção são atendidas.

        === CONTEXTO ===
        Tema: {domain_name}
        Descrição: {domain_description}

        === PERFIL DO ALUNO ===
        {student_profile_summary}

        === SITUAÇÃO ATUAL ===
        {performance_summary}
        {history_instruction}

        === OPÇÕES DISPONÍVEIS ===
        {tactics_joined}

        === REGRAS (Só siga as regras abaixo se não ===
        1. Sempre dê prefência as taticas de Reuso, por exemplo, se houver mais de uma tatica de Reuso, sempre começe por elas intercalando com debatesicrono (se houver).
        2. Considere o tempo disponível.
        3. Se o desempenho for RUIM, simplifique. Se for BOM, aprofunde.
        4. Quando as taticas disponíveis acabarem, encerre a sessão.
        

        === SAÍDA (JSON) ===
        Responda APENAS:
        {{
            "chosen_tactic_id": 0,
            "tactic_name": "Nome",
            "reasoning": "Por que escolheu esta baseado no histórico e notas."
        }} 
        """
        
        # 4. Olhe para o "Táticas já realizadas" para não repetir as taticas.
        # 1. Não seja linear na escolha das taticas, ou seja, escolha as tatica de maneira que melhore o aprendizado.
        # 3. Olhe para o "Táticas já realizadas" para não repetir as taticas.

        # logging.warning("WARNING aparece")
        # logging.info("INFO aparece?")

        logging.info(f"Prompt enviado ao LLM: {prompt}")


        # return jsonify({"prompt": prompt}), 200  # DEBUG: Retorna o prompt para verificação

        # --- 4. Chamada LLM ---
        client = OpenAI(
            api_key=Config.GROQ_API_KEY,
            base_url="https://api.groq.com/openai/v1"
        )
        
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "Responda apenas JSON."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.2 
        )

        content_text = response.choices[0].message.content
        decision_json = json.loads(content_text)


        # --- 5. Chamada ao Gemini ---
        # if not Config.GEMINI_API_KEY:
        #      return jsonify({"error": "GEMINI_API_KEY não configurada"}), 500

        # client = genai.Client(api_key=Config.GEMINI_API_KEY)
        # response = client.models.generate_content(
        #     model="gemini-2.5-flash-lite-preview-09-2025", 
        #     contents=prompt,
        #     config={'response_mime_type': 'application/json'}
        # )
        
        # decision_json = json.loads(response.text)

        return jsonify({
            "success": True,
            "decision": decision_json,
            "history_context_used": executed_names_list
        }), 200

    except Exception as e:
        logging.error(f"Erro no Agente Strategies: {str(e)}")
        return jsonify({"error": str(e)}), 500
    finally:
        if conn:
            conn.close()





@agente_strategies_bp.route('/agent/decide_rules_logic', methods=['POST'])
def decide_rules_logic():
    """
    Agente de Regras (Inteligente):
    - Se Reforço: Escolhe QUAL tática anterior é a melhor para sanar a dúvida.
    - Se Avanço: Escolhe a próxima estratégia baseada no 'score' (qualidade).
    """
    data = request.get_json()

    # --- 1. Extração do Contexto ---
    performance_summary = data.get('performance_summary', 'Sem dados.')
    student_profile = data.get('student_profile_summary', 'Perfil desconhecido.')
    individual_student_summary = data.get('individual_student_summary', 'Perfil individual não disponível.')
    student_score_summary = data.get('student_score_summary', 'Sem notas registradas.')
    domain_content = data.get('article_text', '')
    total_tactics = data.get('total_tactics', 0)

    current_strategy_id = data.get('strategy_id')
    executed_tactics_ids = data.get('executed_tactics', [])

    conn = None
    try:
        db_url = current_app.config.get("SQLALCHEMY_DATABASE_URI") or os.getenv("DATABASE_URL")
        conn = create_connection(db_url)
        
        if not conn:
            return jsonify({"error": "Falha na conexão com o banco"}), 500

        with conn.cursor() as cur:
            # A. Todas as táticas repetíveis da estratégia (exceto Regra e Mudança de Estratégia)
            repeatable_options = []
            if current_strategy_id:
                cur.execute("""
                    SELECT id, name, description
                    FROM tactics
                    WHERE strategy_id = %s
                    AND name NOT ILIKE '%%mudanc%%'
                    AND LOWER(TRIM(name)) NOT IN ('regra', 'regras')
                    ORDER BY id
                """, (int(current_strategy_id),))
                rows = cur.fetchall()
                for r in rows:
                    r_id = r['id'] if isinstance(r, dict) else r[0]
                    r_name = r['name'] if isinstance(r, dict) else r[1]
                    r_desc = r['description'] if isinstance(r, dict) else r[2]
                    repeatable_options.append(f"- ID {r_id}: {r_name} ({r_desc or 'sem descrição'})")

            # B. Outras Estratégias Disponíveis (Opções para Avanço)
            # IMPORTANTE: Agora buscamos o 'score' para priorizar as melhores
            if current_strategy_id:
                cur.execute("""
                    SELECT id, name, score 
                    FROM strategies 
                    WHERE id != %s
                    ORDER BY score DESC
                """, (int(current_strategy_id),))
                strat_rows = cur.fetchall()
                available_strategies = []
                for r in strat_rows:
                    s_id = r['id'] if isinstance(r, dict) else r[0]
                    s_name = r['name'] if isinstance(r, dict) else r[1]
                    s_score = r['score'] if isinstance(r, dict) else r[2]
                    # Formata: "Estratégia X (ID 10) - Nota: 9"
                    available_strategies.append(f"- ID {s_id}: {s_name} (Nota de Qualidade: {s_score})")
            else:
                available_strategies = ["Nenhuma estratégia extra disponível."]

        # --- 2. Cliente Groq ---
        if not Config.GROQ_API_KEY:
             return jsonify({"error": "GROQ_API_KEY não configurada"}), 500

        client = OpenAI(
            api_key=Config.GROQ_API_KEY,
            base_url="https://api.groq.com/openai/v1"
        )

        # --- 3. Prompt Avançado ---
        prompt = f"""
        Você é o 'Agente de Regras' (Cérebro da Sessão) de um Sistema Tutor Inteligente.

        === ALUNO ATUAL ===
        {individual_student_summary}

        === NOTAS DO ALUNO NESTA SESSÃO ===
        {student_score_summary}

        === PERFIL DA TURMA ===
        {student_profile}

        === DESEMPENHO GERAL DA SESSÃO ===
        {performance_summary}

        === CONTEÚDO DA AULA ===
        {domain_content}

        === OPÇÕES DE TÁTICAS QUE PODEM SER REPETIDAS ===
        {chr(10).join(repeatable_options) if repeatable_options else "Nenhuma tática disponível para repetição."}

        === OPÇÕES DE PRÓXIMA ESTRATÉGIA ===
        {chr(10).join(available_strategies)}

        === SUA MISSÃO (REGRA DE DECISÃO) ===
        Analise as NOTAS DO ALUNO, o perfil individual, o desempenho e o conteúdo para decidir:

        1. Se a nota do aluno for BAIXA (abaixo de 70%) ou o desempenho for RUIM → escolha "REPEAT_TACTIC".
           * Escolha a tática da lista "OPÇÕES DE TÁTICAS QUE PODEM SER REPETIDAS" que melhor corrige a dificuldade do aluno.
           * Considere o perfil individual: se o aluno prefere vídeos, prefira táticas visuais; se prefere texto, prefira Reuso com PDFs.
           * IMPORTANTE: após a tática repetida ser concluída, a sessão será encerrada automaticamente para este aluno.

        2. Se a nota do aluno for BOA (70% ou acima) ou o desempenho for BOM/ALTO → escolha "NEXT_STRATEGY".
           * Escolha a estratégia da lista "OPÇÕES DE PRÓXIMA ESTRATÉGIA" com maior Nota de Qualidade (Score).
           * Se o perfil individual exigir algo específico, priorize isso.

        3. Se todas as táticas disponíveis ({total_tactics} no total) já foram executadas, ou se a nota for excelente E não houver próxima estratégia disponível → escolha "END_SESSION".
           * "END_SESSION" significa encerrar imediatamente a participação deste aluno nesta sessão.

        === SAÍDA (JSON OBRIGATÓRIO) ===
        {{
            "decision": "REPEAT_TACTIC" ou "NEXT_STRATEGY" ou "END_SESSION",
            "target_id": <ID inteiro da tática ou estratégia escolhida, ou null para END_SESSION>,
            "target_name": "<Nome da opção escolhida, ou 'Encerrar Sessão' para END_SESSION>",
            "reasoning": "<Explique a decisão considerando o perfil individual do aluno>"
        }}
        """

        # return jsonify({"debug_prompt": prompt}), 200  # DEBUG: Retorna o prompt gerado

        logging.info(f"Prompt enviado ao LLM de Regras: {prompt}")

        # --- 4. Chamada LLM ---
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "Responda apenas JSON."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.2 
        )

        content_text = response.choices[0].message.content
        decision_json = json.loads(content_text)

        return jsonify({
            "success": True,
            "rule_execution": decision_json
        }), 200

    except Exception as e:
        logging.error(f"Erro no Agente Rules: {str(e)}")
        return jsonify({"error": str(e)}), 500
    finally:
        if conn:
            conn.close()


@agente_strategies_bp.route('/students/<string:username>/chat_history', methods=['GET'])
def get_student_chat_history(username):
    """
    Retorna todo o histórico de chat (Geral e Privado) de um aluno,
    agrupado pelo ID DA TÁTICA.
    
    Estrutura de Retorno:
    {
        "tactic_id_1": {
            "tactic_name": "Debate Sincrono",
            "general": ["msg1", "msg2"],
            "private": ["(Para Professor): duvida"]
        },
        "tactic_id_5": { ... }
    }
    """
    conn = None
    try:
        db_url = current_app.config.get("SQLALCHEMY_DATABASE_URI") or os.getenv("DATABASE_URL")
        conn = create_connection(db_url)
        
        if not conn:
            return jsonify({"error": "Falha na conexão com o banco"}), 500

        with conn.cursor() as cur:
            # Dicionário principal: Chave será o ID da Tática (String)
            history_map = {}

            # ---------------------------------------------------------
            # 1. Buscar Mensagens Gerais (Com JOIN na tabela Tactics)
            # ---------------------------------------------------------
            # Precisamos do JOIN para saber qual é o tactic_id associado ao chat (message_id)
            cur.execute("""
                SELECT t.id as tactic_id, t.name as tactic_name, gm.content 
                FROM general_message gm
                JOIN tactics t ON gm.message_id = t.chat_id
                WHERE gm.username = %s
                ORDER BY gm.timestamp ASC
            """, (username,))
            
            gen_rows = cur.fetchall()
            for row in gen_rows:
                # Tratamento seguro (Dict vs Tupla)
                tid = str(row['tactic_id'] if isinstance(row, dict) else row[0])
                tname = row['tactic_name'] if isinstance(row, dict) else row[1]
                content = row['content'] if isinstance(row, dict) else row[2]
                
                # Inicializa a tática no mapa se não existir
                if tid not in history_map:
                    history_map[tid] = {
                        "tactic_name": tname,
                        "general": [], 
                        "private": []
                    }
                
                history_map[tid]["general"].append(content)

            # ---------------------------------------------------------
            # 2. Buscar Mensagens Privadas (Com JOIN na tabela Tactics)
            # ---------------------------------------------------------
            cur.execute("""
                SELECT t.id as tactic_id, t.name as tactic_name, pm.target_username, pm.content 
                FROM private_message pm
                JOIN tactics t ON pm.message_id = t.chat_id
                WHERE pm.username = %s
                ORDER BY pm.timestamp ASC
            """, (username,))
            
            priv_rows = cur.fetchall()
            for row in priv_rows:
                # Tratamento seguro (Dict vs Tupla)
                tid = str(row['tactic_id'] if isinstance(row, dict) else row[0])
                tname = row['tactic_name'] if isinstance(row, dict) else row[1]
                target = row['target_username'] if isinstance(row, dict) else row[2]
                content = row['content'] if isinstance(row, dict) else row[3]
                
                if tid not in history_map:
                    history_map[tid] = {
                        "tactic_name": tname,
                        "general": [], 
                        "private": []
                    }
                
                formatted_msg = f"(Mensagem privada): {content}"
                history_map[tid]["private"].append(formatted_msg)

        # 3. LLM Analysis
        analysis_text = "Análise indisponível"
        try:
            if getattr(Config, 'GROQ_API_KEY', None):
                client = OpenAI(
                    api_key=Config.GROQ_API_KEY,
                    base_url="https://api.groq.com/openai/v1"
                )

                # Truncate if too long to avoid token limit errors
                history_str = str(history_map)
                if len(history_str) > 6000:
                    history_str = history_str[:6000] + "... (truncated)"

                prompt = f"""
                Você é um psicopedagogo.
                Analise as mensagens do aluno no chat. Identifique o nível de engajamento, sentimento (frustração, empolgação) e se ele costuma pedir ajuda ou colaborar.

                Histórico (Tática -> Mensagens):
                {history_str}

                Responda com um parágrafo conciso.
                """

                resp = client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.2
                )
                analysis_text = resp.choices[0].message.content
        except Exception as llm_err:
            logging.warning(f"LLM Error in chat_history: {llm_err}")

        return jsonify({
            "student_engagement_analysis": analysis_text,
            "raw_chat_by_tactic": history_map
        }), 200

    except Exception as e:
        logging.error(f"Erro ao buscar histórico de chat do aluno {username}: {str(e)}")
        return jsonify({"error": str(e)}), 500
    finally:
        if conn:
            conn.close()
