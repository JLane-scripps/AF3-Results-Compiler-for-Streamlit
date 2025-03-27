import streamlit as st
import pandas as pd
import zipfile
import psutil, os
import io
import json
import re
import gc
# Uncomment if you want to use ijson for streaming JSON parsing
# import ijson

# --- Helper Function ---
def extract_bait_prey(file_identifier):
    """
    Extracts bait and prey names from a file identifier.
    Expected pattern: ..._bait_<Bait>_prey_<Prey>_summary_confidences_4.json
    This regex excludes '/' and '\' but allows underscores.
    """
    if "::" in file_identifier:
        filename = os.path.basename(file_identifier.split("::")[-1])
    else:
        filename = os.path.basename(file_identifier)
    pattern = r'bait_([^/\\]+)_prey_([^/\\]+)(?=_summary_confidences_4)'
    match = re.search(pattern, filename)
    if match:
        return match.group(1), match.group(2)
    else:
        return None, None

# --- Session State Initialization ---
if "processed_records" not in st.session_state:
    st.session_state.processed_records = []  # List of dictionaries from processed JSON files.
if "processed_file_names" not in st.session_state:
    st.session_state.processed_file_names = []  # Names of ZIP files already processed.
if "debug_messages" not in st.session_state:
    st.session_state.debug_messages = []

# Debug log container
debug_container = st.empty()
def update_debug_log(message):
    st.session_state.debug_messages.append(message)
    debug_container.text_area("Debug Log", "\n".join(st.session_state.debug_messages), height=150)

# --- Display System Memory ---
memory_info = psutil.virtual_memory()
available_mb = memory_info.available / 1024**2
st.write(f"**Max Available RAM:** {available_mb:.2f} MB")
process = psutil.Process(os.getpid())
st.write(f"Memory at newest upload: {process.memory_info().rss / 1024**2:.2f} MB")

# --- File Uploader for ZIP Files ---
uploaded_zip_files = st.file_uploader("Upload ZIP files", type=["zip"], accept_multiple_files=True)

# --- File Uploader for Existing Excel Files (Optional) ---
uploaded_excel_files = st.file_uploader("Upload existing Excel files to combine (optional)", type=["xlsx"], accept_multiple_files=True)

# --- Process Uploaded ZIP Files Immediately Using Streaming ---
if uploaded_zip_files:
    update_debug_log(f"Memory before processing ZIPs: {process.memory_info().rss / 1024**2:.2f} MB")
    for file in uploaded_zip_files:
        if file.name not in st.session_state.processed_file_names:
            update_debug_log(f"Processing file: {file.name}")
            try:
                # Use the uploaded file object directly without reading it entirely into a new BytesIO.
                with zipfile.ZipFile(file) as z:
                    for item in z.namelist():
                        # Process only the nested JSON file we need.
                        if item.endswith("summary_confidences_4.json"):
                            file_identifier = f"{file.name}::{os.path.basename(item)}"
                            update_debug_log(f"  Reading: {file_identifier}")
                            try:
                                with z.open(item) as f:
                                    # If the JSON files are very large, you could use a streaming parser like ijson:
                                    # parser = ijson.parse(f)
                                    # data = {}  # Build your JSON object piece by piece.
                                    # For now, we assume the JSON file is reasonably small:
                                    data = json.load(f)
                            except Exception as e:
                                st.error(f"Error decoding JSON in {file_identifier}: {e}")
                                update_debug_log(f"Error decoding JSON in {file_identifier}: {e}")
                                continue

                            bait, prey = extract_bait_prey(file_identifier)
                            if bait is None or prey is None:
                                st.warning(f"DEBUG: Could not extract bait/prey from {file_identifier}")
                                update_debug_log(f"DEBUG: Could not extract bait/prey from {file_identifier}")
                                bait, prey = "Unknown", "Unknown"

                            record = {
                                "Bait": bait,
                                "Prey": prey,
                                "iptm": data.get("iptm"),
                                "pair iptm": data.get("ptm"),
                                "fraction disordered": data.get("fraction_disordered"),
                                "hash clash": data.get("has_clash"),
                                "ranking score": data.get("ranking_score"),
                                "chain iptm": json.dumps(data.get("chain_iptm")),
                                "chain ptm": json.dumps(data.get("chain_ptm")),
                                "chain pair iptm": json.dumps(data.get("chain_pair_iptm")),
                                "chain pair pae min": json.dumps(data.get("chain_pair_pae_min"))
                            }
                            st.session_state.processed_records.append(record)
                st.session_state.processed_file_names.append(file.name)
                update_debug_log(f"Finished processing: {file.name}")
            except Exception as e:
                st.error(f"Error processing file {file.name}: {e}")
                update_debug_log(f"Error processing file {file.name}: {e}")
            finally:
                try:
                    file.close()
                except Exception:
                    pass
                gc.collect()
                update_debug_log(f"Memory after cleanup: {process.memory_info().rss / 1024**2:.2f} MB")

# --- Display Processed ZIP File Names ---
if st.session_state.processed_file_names:
    st.write("### Processed ZIP Files:")
    for name in st.session_state.processed_file_names:
        st.write(name)

# --- Generate Excel Button ---
if st.session_state.processed_records or uploaded_excel_files:
    if st.button("Generate Excel"):
        # Build DataFrame from processed ZIP data.
        df_zip = pd.DataFrame(st.session_state.processed_records) if st.session_state.processed_records else pd.DataFrame()
        df_existing_list = []
        if uploaded_excel_files:
            for excel_file in uploaded_excel_files:
                try:
                    df_existing = pd.read_excel(excel_file)
                    df_existing_list.append(df_existing)
                except Exception as e:
                    st.error(f"Error reading Excel file {excel_file.name}: {e}")
        if df_existing_list:
            df_existing_all = pd.concat(df_existing_list, ignore_index=True)
            combined_df = pd.concat([df_zip, df_existing_all], ignore_index=True)
        else:
            combined_df = df_zip

        combined_df = combined_df.sort_values(by="iptm", ascending=False)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            workbook = writer.book
            format_light_yellow = workbook.add_format({'bg_color': '#FFFF99'})
            format_light_blue   = workbook.add_format({'bg_color': '#ADD8E6'})
            format_light_gray   = workbook.add_format({'bg_color': '#D3D3D3'})

            for bait, group_df in combined_df.groupby("Bait"):
                sheet_name = str(bait)[:31]
                group_df.to_excel(writer, sheet_name=sheet_name, index=False)
                worksheet = writer.sheets[sheet_name]
                num_rows = len(group_df) + 1
                iptm_range = f"C2:C{num_rows}"
                worksheet.conditional_format(iptm_range, {
                    'type': 'cell',
                    'criteria': '>',
                    'value': 0.79,
                    'format': format_light_yellow
                })
                worksheet.conditional_format(iptm_range, {
                    'type': 'cell',
                    'criteria': 'between',
                    'minimum': 0.6,
                    'maximum': 0.79,
                    'format': format_light_blue
                })
                worksheet.conditional_format(iptm_range, {
                    'type': 'formula',
                    'criteria': '=AND(C2>0.4, C2<0.6)',
                    'format': format_light_gray
                })
        output.seek(0)
        processed_data = output.getvalue()
        st.download_button(
            label="Download Consolidated Excel File",
            data=processed_data,
            file_name="summary_confidences_export.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
