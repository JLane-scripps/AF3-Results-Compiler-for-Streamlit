import streamlit as st
import pandas as pd
import zipfile
import io
import json
import re
import os


def extract_bait_prey(file_identifier):
    """
    Extract bait and prey names from a file identifier.
    The file identifier should be like: "zipname.zip::fold_pair_4_bait_o00499_prey_p38646_summary_confidences_4.json"
    This regex ensures that '/' and '\' are not included in the extracted groups,
    but allows underscores in the names (for example, "p42658_2").
    """
    # For zip files, use only the basename of the internal file.
    if "::" in file_identifier:
        filename = os.path.basename(file_identifier.split("::")[-1])
    else:
        filename = os.path.basename(file_identifier)
    pattern = r'bait_([^/\\]+)_prey_([^/\\]+)(?=_summary_confidences_4)'
    match = re.search(pattern, filename)
    if match:
        bait = match.group(1)
        prey = match.group(2)
        return bait, prey
    else:
        return None, None


st.title("Upload Zipped Folders Containing JSON Files")
st.write("Drag and drop ZIP files (or click to browse) containing your summary JSON files.")

# Allow users to upload multiple ZIP files
uploaded_files = st.file_uploader("Upload ZIP files", type=["zip"], accept_multiple_files=True)

if uploaded_files:
    results = []
    for uploaded_file in uploaded_files:
        st.write(f"Processing ZIP file: **{uploaded_file.name}**")
        try:
            # Open the uploaded file as a ZIP archive.
            with zipfile.ZipFile(uploaded_file) as z:
                for item in z.namelist():
                    # Process only files ending with "summary_confidences_4.json"
                    if item.endswith("summary_confidences_4.json"):
                        file_identifier = f"{uploaded_file.name}::{os.path.basename(item)}"
                        st.write(f"Processing file: **{file_identifier}**")
                        try:
                            with z.open(item) as f:
                                data = json.load(f)
                        except Exception as e:
                            st.error(f"Error decoding JSON in {file_identifier}: {e}")
                            continue

                        bait, prey = extract_bait_prey(file_identifier)
                        if bait is None or prey is None:
                            st.warning(f"DEBUG: Could not extract bait/prey from file: {file_identifier}")
                            bait, prey = "Unknown", "Unknown"

                        # Build the record using the desired column mapping
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
                        results.append(record)
        except Exception as e:
            st.error(f"Error processing ZIP file {uploaded_file.name}: {e}")

    if results:
        df = pd.DataFrame(results)
        st.write("### Extracted Data:")
        st.dataframe(df)

        # Create an in-memory Excel file with conditional formatting
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, sheet_name='Sheet1', index=False)
            workbook = writer.book
            worksheet = writer.sheets['Sheet1']

            # Determine the number of rows (header is row 1, data starts in row 2)
            num_rows = len(df) + 1
            # "iptm" is the 3rd column (Excel column C)
            iptm_range = f"C2:C{num_rows}"

            # Define cell formats with the revised colors
            format_light_yellow = workbook.add_format({'bg_color': '#FFFF99'})
            format_light_blue = workbook.add_format({'bg_color': '#ADD8E6'})
            format_light_gray = workbook.add_format({'bg_color': '#D3D3D3'})

            # Apply conditional formatting:
            # Rule 1: iptm > 0.79: light yellow
            worksheet.conditional_format(iptm_range, {
                'type': 'cell',
                'criteria': '>',
                'value': 0.79,
                'format': format_light_yellow
            })
            # Rule 2: 0.79 >= iptm >= 0.6: light blue
            worksheet.conditional_format(iptm_range, {
                'type': 'cell',
                'criteria': 'between',
                'minimum': 0.6,
                'maximum': 0.79,
                'format': format_light_blue
            })
            # Rule 3: 0.6 > iptm > 0.4: light gray (strict inequality)
            worksheet.conditional_format(iptm_range, {
                'type': 'formula',
                'criteria': '=AND(C2>0.4, C2<0.6)',
                'format': format_light_gray
            })

            writer.save()
            processed_data = output.getvalue()

        st.download_button(
            label="Download Excel File",
            data=processed_data,
            file_name="summary_confidences_export.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    else:
        st.info("No valid JSON files found in the uploaded ZIP files.")
