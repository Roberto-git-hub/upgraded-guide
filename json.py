import streamlit as st
import pandas as pd
import json
import base64
import zlib
from collections import Counter

# =====================================================================
# INTERFACE STREAMLIT - MODO LEITOR DE LINK (Operador)
# =====================================================================
st.set_page_config(page_title="Gerador JSON - Adobe Campaign", layout="centered", page_icon="⚙️")

# Se existir o parâmetro 'data' na URL, ele entra no modo "Leitor de JSON"
if 'data' in st.query_params:
    try:
        # Pega os dados da URL, descompacta (zlib) e decodifica (base64)
        compressed_data = base64.urlsafe_b64decode(st.query_params['data'])
        json_string = zlib.decompress(compressed_data).decode('utf-8')
        
        st.title("📄 Visualizador de JSON (Workflow)")
        st.success("JSON carregado com sucesso via link!")
        st.warning("💡 COMO COPIAR: Passe o mouse no canto superior direito do bloco preto abaixo e clique no ícone de prancheta (📋) para copiar tudo.")
        
        # Mostra apenas o código e interrompe o resto do app
        st.code(json_string, language='json')
        st.stop() 
    except Exception as e:
        st.error("⚠️ O link parece estar quebrado ou corrompido. Peça para gerar novamente.")
        st.stop()


# =====================================================================
# FUNÇÕES DE PROCESSAMENTO (Coordenadora)
# =====================================================================
def load_and_clean_data(uploaded_file):
    if uploaded_file.name.endswith('.csv'):
        try:
            df = pd.read_csv(uploaded_file, sep=None, engine='python')
        except:
            df = pd.read_csv(uploaded_file, sep=';')
    else:
        df = pd.read_excel(uploaded_file)

    first_col = str(df.columns[0]).lower()
    if 'unnamed' in first_col or 'deployment' in first_col:
        for idx, row in df.iterrows():
            row_values = [str(val).lower().strip() for val in row.values]
            if any(k in row_values for k in ['dag segment name', 'segment name', 'cellname', 'waterfall order']):
                df.columns = df.iloc[idx]
                df = df.iloc[idx + 1:].reset_index(drop=True)
                break

    return df

def process_data(df):
    final_json_data = []
    waterfall_id = 1

    cols = {str(c).strip().lower(): c for c in df.columns}

    def get_val(row, possible_names):
        for name in possible_names:
            actual_col = cols.get(name.lower())
            if actual_col is not None:
                val = str(row.get(actual_col, '')).strip()
                if val.lower() != 'nan' and val != '':
                    return val
        return ''

    for _, row in df.iterrows():
        # HARD STOP: Para a leitura se chegar na área de referência
        row_text = ' '.join([str(val).lower() for val in row.values])
        if 'reference for combination' in row_text or 'suppression segments' in row_text:
            break  

        # FILTRO N/A: Pula linhas onde o Waterfall Order for "N/A"
        waterfall_order = get_val(row, ['Waterfall Order', 'WaterfallOrder'])
        if waterfall_order.lower() == 'n/a':
            continue  

        segment_code = get_val(row, ['Segment Code', 'SegmentCode', 'Additional SegmentCode'])
        
        if not segment_code:
            continue

        dag_segment_name = get_val(row, ['DAG Segment Name', 'Segment Name', 'DAGSegmentName'])
        cell_name = get_val(row, ['CellName', 'Cell Name'])
        source = get_val(row, ['Source'])
        requested_volume = get_val(row, ['Requested Volume', 'Requested', 'Testing split', 'Split'])
        sline_code = get_val(row, ['SlineCode', 'Sline Code', 'SL Code'])

        if not dag_segment_name and not cell_name:
            continue

        check_str = (dag_segment_name or cell_name).lower()
        if check_str.startswith('where ') or check_str.startswith('pick from') or check_str.startswith('and '):
            continue

        if not dag_segment_name: dag_segment_name = cell_name
        if not cell_name: cell_name = dag_segment_name

        # LIMPEZA DE CARACTERES ESPECIAIS
        dag_segment_name = dag_segment_name.replace('&', 'AND').replace(' ', '_')
        cell_name = cell_name.replace('&', 'AND').replace(' ', '_')

        dag_count_col = None
        for name in ['dag count', 'count']:
            if name in cols:
                dag_count_col = cols[name]
                break
                
        dag_count_raw = row.get(dag_count_col, 0) if dag_count_col else 0
        try:
            if pd.isna(dag_count_raw):
                dag_count = 0.0
            elif isinstance(dag_count_raw, (int, float)):
                dag_count = float(dag_count_raw)
            else:
                cleaned = str(dag_count_raw).replace(',', '').replace('.', '').strip()
                dag_count = float(cleaned) if cleaned else 0.0
        except:
            dag_count = 0.0

        seg_code_lower = segment_code.lower()
        has_split_in_code = (
            "50%:" in seg_code_lower or 
            "50%" in seg_code_lower or 
            "/" in segment_code or 
            "\n" in segment_code
        )

        req_vol_str = str(requested_volume).lower().replace(',', '.')
        has_split_in_volume = (
            "50%" in req_vol_str or 
            "50/50" in req_vol_str or 
            req_vol_str == "0.5" or 
            req_vol_str == "0.50" or
            req_vol_str == "50"
        )

        is_split = has_split_in_code or has_split_in_volume

        if is_split:
            if "\n" in segment_code:
                parts = [x.strip() for x in segment_code.split("\n") if x.strip()]
            elif "/" in segment_code:
                parts = [x.strip() for x in segment_code.split("/", 1)]
            else:
                parts = [segment_code, segment_code]

            code1 = parts[0].replace("50%:", "").replace("50%", "").strip()
            code2 = parts[1] if len(parts) > 1 else code1
            code2 = code2.replace("50%:", "").replace("50%", "").strip()

            records = [
                {
                    "WaterfallId": waterfall_id,
                    "DAGSegmentName": dag_segment_name,
                    "CellName": cell_name,
                    "Split": 0.5,
                    "SegmentCode": code1,
                    "SlineCode": sline_code
                },
                {
                    "WaterfallId": waterfall_id + 1,
                    "DAGSegmentName": dag_segment_name,
                    "CellName": f"{cell_name}_Test",
                    "Split": 0.5,
                    "SegmentCode": code2,
                    "SlineCode": sline_code
                }
            ]
            waterfall_id += 2

            for r in records:
                if source.upper() != "ACM":
                    r["DAGSCount"] = dag_count
                    r["isABTest"] = "FALSE"
                r.update({"extraColumnA": "", "extraColumnB": "", "extraColumnC": ""})
                final_json_data.append(r)

        else:
            code = segment_code.replace("100%:", "").strip()
            record = {
                "WaterfallId": waterfall_id,
                "DAGSegmentName": dag_segment_name,
                "CellName": cell_name,
                "Split": 1.0,
                "SegmentCode": code,
                "SlineCode": sline_code
            }
            waterfall_id += 1

            if source.upper() != "ACM":
                record["DAGSCount"] = dag_count
                record["isABTest"] = "FALSE"
            record.update({"extraColumnA": "", "extraColumnB": "", "extraColumnC": ""})
            final_json_data.append(record)

    return final_json_data

# =====================================================================
# INTERFACE STREAMLIT - MODO CRIADOR (Coordenadora)
# =====================================================================
st.title("⚙️ Segment-to-JSON Converter")
st.write("Faça o upload da planilha para auditar, gerar a estrutura JSON e o Link Direto.")

uploaded_file = st.file_uploader("Selecione o arquivo fonte", type=["xlsx", "csv"])

if uploaded_file is not None:
    try:
        df = load_and_clean_data(uploaded_file)
        st.success("Arquivo carregado com sucesso!")
        
        if st.button("Analisar e Gerar JSON"):
            json_objects = process_data(df)
            
            # =================================================================
            # 1. VALIDAÇÃO PROATIVA (O FISCAL)
            # =================================================================
            st.divider()
            st.subheader("🕵️‍♂️ Auditoria da Planilha")
            
            errors = []
            warnings = []
            
            # Checagem de SegmentCode Duplicado
            segment_codes = [obj.get("SegmentCode", "") for obj in json_objects]
            counts = Counter(segment_codes)
            duplicates = [code for code, count in counts.items() if count > 1 and code != ""]
            
            if duplicates:
                errors.append(f"Códigos de Segmento Duplicados (Causa erro no Adobe): {', '.join(duplicates)}")
                
            # Checagem de campos obrigatórios vazios
            for obj in json_objects:
                if not obj.get("CellName"):
                    warnings.append(f"CellName vazio no WaterfallId {obj.get('WaterfallId')}")
                if not obj.get("SlineCode"):
                    warnings.append(f"SlineCode vazio no WaterfallId {obj.get('WaterfallId')}")
                    
            # Exibição dos alertas
            if errors:
                st.error("🚨 Erros Críticos Encontrados. Corrija a planilha antes de gerar o link!")
                for e in errors:
                    st.write(f"- {e}")
                st.stop() # Bloqueia a aplicação aqui se tiver erro fatal
                
            if warnings:
                st.warning("⚠️ Avisos de Preenchimento (Verifique se é proposital):")
                for w in warnings:
                    st.write(f"- {w}")
                    
            if not errors and not warnings:
                st.success("✅ Planilha impecável! Nenhuma anomalia estrutural encontrada.")

            # =================================================================
            # 2. DASHBOARD DE AUDITORIA (RAIO-X VISUAL)
            # =================================================================
            st.divider()
            st.subheader("📊 Raio-X da Campanha")
            
            total_segments = len(json_objects)
            total_ab_tests = sum(1 for obj in json_objects if obj.get("Split") == 0.5) // 2
            total_volume = sum(float(obj.get("DAGSCount", 0)) for obj in json_objects)
            
            col1, col2, col3 = st.columns(3)
            col1.metric("Total de Segmentos", total_segments)
            col2.metric("Testes A/B (Pares)", total_ab_tests)
            col3.metric("Volume Estimado", f"{total_volume:,.0f}".replace(",", "."))
            
            if total_volume > 0:
                st.write("**Distribuição Estimada por Segmento:**")
                chart_data = pd.DataFrame({
                    "Segmento": [obj.get("CellName") for obj in json_objects],
                    "Volume": [float(obj.get("DAGSCount", 0)) for obj in json_objects]
                })
                # Plota o gráfico com o Segmento no eixo X
                st.bar_chart(chart_data.set_index("Segmento"))

            # =================================================================
            # 3. GERAÇÃO DO LINK E JSON
            # =================================================================
            json_string = json.dumps(json_objects, indent=2)

            APP_URL = "https://upgraded-guide-bxpthdptstyfwaor2naznv.streamlit.app"
            compressed_data = zlib.compress(json_string.encode('utf-8'))
            encoded_data = base64.urlsafe_b64encode(compressed_data).decode('utf-8')
            shareable_link = f"{APP_URL}?data={encoded_data}"

            st.divider()
            st.subheader("🔗 Seu Link de Compartilhamento")
            st.info("Copie o link abaixo e cole na planilha. Quem clicar verá diretamente o JSON.")
            st.code(shareable_link, language='text')

            st.divider()
            st.subheader("📄 Resultado (JSON Bruto):")
            st.code(json_string, language='json')
            
            st.download_button(
                label="📥 Baixar Arquivo .json",
                data=json_string,
                file_name="dataSegments_output.json",
                mime="application/json",
                use_container_width=True
            )

    except Exception as e:
        st.error(f"Ocorreu um erro ao processar o arquivo: {e}")
