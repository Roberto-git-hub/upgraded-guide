import streamlit as st
import pandas as pd
import json

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
        # =====================================================================
        # 1. HARD STOP (Quebra-Mola): Para a leitura se chegar na área de referência
        # =====================================================================
        row_text = ' '.join([str(val).lower() for val in row.values])
        if 'reference for combination' in row_text or 'suppression segments' in row_text:
            break  # Interrompe o loop imediatamente. O JSON acaba aqui!

        # =====================================================================
        # 2. FILTRO N/A: Pula linhas onde o Waterfall Order for "N/A"
        # =====================================================================
        waterfall_order = get_val(row, ['Waterfall Order', 'WaterfallOrder'])
        if waterfall_order.lower() == 'n/a':
            continue  # Pula esta linha e vai para a próxima

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

        # =====================================================================
        # 3. LIMPEZA DE CARACTERES ESPECIAIS (Evita quebra de XML no Adobe)
        # =====================================================================
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
# INTERFACE WEB STREAMLIT
# =====================================================================
st.set_page_config(page_title="Gerador JSON - Adobe Campaign", layout="centered")

st.title("⚙️ Segment-to-JSON Converter")
st.write("Upload your Excel (.xlsx) or CSV file to generate the JSON structure for segments.")

uploaded_file = st.file_uploader("Select the source file", type=["xlsx", "csv"])

if uploaded_file is not None:
    try:
        df = load_and_clean_data(uploaded_file)

        st.success("File uploaded and header successfully identified!")
        st.dataframe(df.head())

        if st.button("To generate JSON"):
            json_objects = process_data(df)
            json_string = json.dumps(json_objects, indent=2)

            st.subheader("Final Result (JSON):")
            
            # Caixa de destaque orientando a equipe sobre como copiar com um clique!
            st.warning("💡 **HOW TO COPY:** Hover your mouse over the **top-right corner** of the dark block below. A clipboard icon (📋) will appear. Click it once to copy the entire code without needing to scroll!")

            # O st.code possui o botão de cópia nativo e já renderiza bonito
            st.code(json_string, language='json')
            
            st.download_button(
                label="📥 Download File .json",
                data=json_string,
                file_name="dataSegments_output.json",
                mime="application/json",
                use_container_width=True
            )

    except Exception as e:
        st.error(f"Ocorreu um erro ao processar o arquivo: {e}")
