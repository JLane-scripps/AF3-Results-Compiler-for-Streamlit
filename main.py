import streamlit as st
import pandas as pd
import zipfile
import psutil, os
import io
import json
import re
import gc


# --- Helper Function ---
def extract_bait_prey(file_identifier):
    """
    Extracts bait and prey names from a file identifier.
    Expected pattern: ..._bait_<Bait>_prey_<Prey>_summary_confidences_4.json
    This regex excludes '/' and '\' but allows underscores.
    """
    # For ZIP-internal files, work with the basename only.
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
    st.session_state.processed_file_names = []  # List of names of ZIP files already processed.

# --- App Title and Instructions ---
st.title("AlphaFold3 Results Compiler")
st.write("""
This app compiles Summary Confidence Reports to easily analyze.

Upload the ZIP files downloaded from AlphaFold3. (Drag & Drop or Browse). 
ZIP files MUST be smaller than 2GB each. Do not upload more than a combined 2GB at a time. 
You may continue adding more ZIP files after the previous batch has been processed.  
Each file will be processed immediately upon upload (one at a time), and then its memory will be released.  
The names of processed files will be displayed. Duplicate uploads will be ignored.
When finished, click **Generate Excel** to consolidate all results.
""")

# --- Initialize the debug log list in session state if it doesn't exist. ---
if "debug_messages" not in st.session_state:
    st.session_state.debug_messages = []
# Create an empty container for the debug log.
debug_container = st.empty()
# Record RAM usage before the first upload in the Debug log
process = psutil.Process(os.getpid())
st.write(f"Memory on initialization: {process.memory_info().rss / 1024 ** 2:.2f} MB")

def update_debug_log(message):
    # Append the new message.
    st.session_state.debug_messages.append(message)
    # Update the text area (height can be adjusted as needed).
    debug_container.text_area("Debug Log", "\n".join(st.session_state.debug_messages), height=150)


# --- File Uploader (Multi-file Allowed) ---
uploaded_files = st.file_uploader("Upload ZIP files", type=["zip"], accept_multiple_files=True)

if uploaded_files:
    # Record RAM usage before the newest upload in the Debug log
    process = psutil.Process(os.getpid())
    update_debug_log(f"Memory before processing: {process.memory_info().rss / 1024 ** 2:.2f} MB")
    # Process each uploaded file one by one.
    for file in uploaded_files:
        # Only process files that have not been processed yet. This ignores duplicates.
        if file.name not in st.session_state.processed_file_names:
            update_debug_log(f"Processing file: **{file.name}**")
            try:
                # Read the entire ZIP file into a BytesIO object named "z".
                file_content = file.read()
                zip_bytes = io.BytesIO(file_content)
                with zipfile.ZipFile(zip_bytes) as z:
                    for item in z.namelist():
                        # ONLY reads the 4th summary_confidences json file, as that is the only one we want.
                        if item.endswith("summary_confidences_4.json"):
                            file_identifier = f"{file.name}::{os.path.basename(item)}"
                            update_debug_log(f"  Reading: **{file_identifier}**")
                            try:
                                with z.open(item) as f:
                                    data = json.load(f)
                            except Exception as e:
                                st.error(f"Error decoding JSON in {file_identifier}: {e}")
                                continue

                            bait, prey = extract_bait_prey(file_identifier)
                            if bait is None or prey is None:
                                st.warning(f"DEBUG: Could not extract bait/prey from {file_identifier}")
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
                update_debug_log(f"Finished processing: **{file.name}**")
                # Catch errors ( "e" ) both with Streamlit and the debug log.
            except Exception as e:
                st.error(f"Error processing file {file.name}: {e}")
                update_debug_log(f"Error processing file {file.name}: {e}")
            finally:
                # Release memory used by this file.
                try:
                    file.close()  # Close the uploaded file.
                except Exception:
                    pass
                del file_content, zip_bytes
                gc.collect()
                update_debug_log(f"Memory after cleanup: {process.memory_info().rss / 1024 ** 2:.2f} MB")

# --- Display Processed File Names ---
if st.session_state.processed_file_names:
    st.write("### Processed Files:")
    for name in st.session_state.processed_file_names:
        st.write(name)

# --- Generate Excel Button ---
if st.session_state.processed_records:
    if st.button("Generate Excel"):
        # Combine all processed records into a DataFrame.
        df = pd.DataFrame(st.session_state.processed_records)
        # Sort the DataFrame by iptm in descending order.
        df = df.sort_values(by="iptm", ascending=False)

        # Create an in-memory Excel file with one sheet per Bait.
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            workbook = writer.book
            # Define conditional formats.
            format_light_yellow = workbook.add_format({'bg_color': '#FFFF99'})
            format_light_blue = workbook.add_format({'bg_color': '#ADD8E6'})
            format_light_gray = workbook.add_format({'bg_color': '#D3D3D3'})

            for bait, group_df in df.groupby("Bait"):
                # Use bait as sheet name (max 31 characters).
                sheet_name = str(bait)[:31]
                group_df.to_excel(writer, sheet_name=sheet_name, index=False)
                worksheet = writer.sheets[sheet_name]
                num_rows = len(group_df) + 1  # +1 for header.
                iptm_range = f"C2:C{num_rows}"  # Assuming 'iptm' is column C.

                # Apply conditional formatting.
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
            label="Download Excel File",
            data=processed_data,
            file_name="summary_confidences_export.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
