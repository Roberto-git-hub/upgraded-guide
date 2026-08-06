import streamlit as st
import pandas as pd
import json
import urllib.request
import urllib.parse

# Roteamento simples: se a URL tiver ?view=raw, exibe apenas o JSON na tela
query_params = st.query_params
if "json_raw" in st.session_state and query_params.get("view") == "raw":
    st.text(st.session_state["json_raw"])
    st.stop()

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

def generate_web_link(json_content):
    """Envia o JSON para o dpaste.org e retorna uma URL pública de leitura"""
    try:
        data = urllib.parse.urlencode({'content': json_content, 'format': 'url', 'expiry': '10'}).encode('utf-8')
        req = urllib.request.Request('https://dpaste.org/api/', data=data)
        with urllib.request.urlopen(req) as response:
            paste_url = response.read().decode('utf-8').strip()
            return f"{paste_url}/raw"
    except Exception:
        return None

# Interface Web Streamlit
st.set_page_config(page_title="Gerador JSON - Adobe Campaign", layout="centered")

st.title("⚙️ Conversor de Segmentos para JSON")
st.write("Faça o upload do seu arquivo Excel (.xlsx) ou CSV para gerar a estrutura JSON de segmentos.")

uploaded_file = st.file_uploader("Escolha o arquivo de origem", type=["xlsx", "csv"])

if uploaded_file is not None:
    try:
        df = load_and_clean_data(uploaded_file)

        st.success("Arquivo carregado e cabeçalho identificado com sucesso!")
        st.dataframe(df.head())

        if st.button("Gerar JSON"):
            json_objects = process_data(df)
            json_string = json.dumps(json_objects, indent=2)
            st.session_state["json_raw"] = json_string

            st.subheader("Resultado Final (JSON):")
            # O bloco abaixo possui o botão de copiar nativo do Streamlit no canto superior direito
            st.code(json_string, language='json')

            col1, col2 = st.columns(2)

            with col1:
                st.download_button(
                    label="📥 Baixar Ficheiro .json",
                    data=json_string,
                    file_name="dataSegments_output.json",
                    mime="application/json",
                    use_container_width=True
                )

            with col2:
                # Gera link público para visualização no navegador
                link_web = generate_web_link(json_string)
                if link_web:
                    st.link_button("🌐 Abrir JSON na Web (Link)", link_web, use_container_width=True)
                else:
                    st.warning("Não foi possível gerar a URL temporária no momento.")

    except Exception as e:
        st.error(f"Ocorreu um erro ao processar o arquivo: {e}")
