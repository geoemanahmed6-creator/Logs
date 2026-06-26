import streamlit as st
import dlisio
import dlisio.lis as lis
import lasio
import numpy as np
import pandas as pd
import io
import tempfile
from pathlib import Path
import zipfile
from datetime import datetime
import re
import plotly.graph_objects as go
from plotly.subplots import make_subplots

st.set_page_config(page_title="Log Converter Pro - Batch", layout="wide")

st.markdown("""
<style>
    .report-box { padding: 15px; border-radius: 10px; margin: 10px 0; }
    .match-perfect { background-color: #d4edda; border: 2px solid #28a745; padding: 10px; border-radius: 10px; }
    .match-warning { background-color: #fff3cd; border: 2px solid #ffc107; padding: 10px; border-radius: 10px; }
    .match-error { background-color: #f8d7da; border: 2px solid #dc3545; padding: 10px; border-radius: 10px; }
</style>
""", unsafe_allow_html=True)

st.title("🛢️ Log Converter Pro - LIS/DLIS to LAS")
st.markdown("يستخدم نفس محركات القراءة الاحترافية لاستخراج الهيدر، أسماء المنحنيات، والوحدات الحقيقية.")

# ============================================================
# المحرك الاحترافي لقراءة LIS و DLIS واستخراج (Header + Units)
# ============================================================
def read_well_file_pro(file_bytes, file_name):
    tmp_path = None
    with tempfile.NamedTemporaryFile(delete=False, suffix='.lis') as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name

    curves = {}
    metadata = {}
    well_info = {'well_name': 'UNKNOWN', 'method': 'UNKNOWN', 'total_curves': 0}
    
    # 1. محاولة القراءة كملف LIS (الطريقة الصحيحة لملفاتك)
    try:
        with lis.load(tmp_path) as f:
            well_info['method'] = "LIS (Logical Parser)"
            for lf in f:
                # محاولة استخراج اسم البئر من الهيدر (Text Records)
                try:
                    for text_record in lf.text:
                        txt = text_record.text.decode('ascii', errors='ignore').strip()
                        # البحث عن النمط WN أو WELL
                        if 'WN ' in txt or 'WELL ' in txt or 'WELLNAME' in txt:
                            match = re.search(r'(?:WN|WELL|WELLNAME)\s+([A-Za-z0-9\-\/]+)', txt)
                            if match: well_info['well_name'] = match.group(1).strip()
                except: pass
                
                # استخراج البيانات والوحدات
                for p in lf.log_passes():
                    try:
                        pass_data = p.curves() # استخراج البيانات كمصفوفة Numpy
                        if isinstance(pass_data, np.ndarray) and pass_data.dtype.names:
                            for name in pass_data.dtype.names:
                                # استخراج الوحدة (Unit)
                                unit = ""
                                desc = name
                                for spec in p.data_specs:
                                    if spec.mnemonic == name:
                                        unit = getattr(spec, 'units', '')
                                        desc = getattr(spec, 'description', name)
                                        break
                                
                                data = pass_data[name]
                                if data.ndim > 1: data = data.flatten()
                                
                                curves[name] = data
                                metadata[name] = {'unit': unit, 'desc': desc}
                    except: continue
            
            if curves: 
                well_info['total_curves'] = len(curves)
                return curves, metadata, well_info, None
    except Exception as e:
        pass # سيفشل إذا لم يكن LIS صالحاً وينتقل لـ DLIS

    # 2. محاولة القراءة كملف DLIS
    try:
        with dlisio.dlis.load(tmp_path) as f:
            well_info['method'] = "DLIS (Logical Parser)"
            for lf in f:
                for origin in getattr(lf, 'origins', []):
                    if getattr(origin, 'well_name', None):
                        well_info['well_name'] = origin.well_name
                        break
                for frame in getattr(lf, 'frames', []):
                    for curve in frame.curves():
                        name = getattr(curve, 'name', '')
                        if name:
                            data = curve.curves()
                            if data.ndim > 1: data = data.flatten()
                            curves[name] = data
                            metadata[name] = {
                                'unit': getattr(curve, 'units', ''),
                                'desc': getattr(curve, 'description', name)
                            }
            if curves:
                well_info['total_curves'] = len(curves)
                return curves, metadata, well_info, None
    except Exception as e:
        return None, None, None, f"فشل في استخراج البيانات: {str(e)}"
    
    return None, None, None, "لم يتم العثور على أي منحنيات قابلة للقراءة في الملف."

# ============================================================
# دالة لتوحيد أطوال المنحنيات (تمنع انهيار التحويل)
# ============================================================
def align_curves(curves):
    valid_curves = {k: v for k, v in curves.items() if len(v) > 0}
    if not valid_curves: return {}, 0
    min_len = min([len(v) for v in valid_curves.values()])
    aligned = {k: v[:min_len] for k, v in valid_curves.items()}
    return aligned, min_len

# ============================================================
# دالة التحويل إلى LAS مع الاعتماد على العمق الحقيقي (DEPT)
# ============================================================
def convert_to_las(file_bytes, file_name, progress_callback=None):
    try:
        curves, metadata, well_info, error = read_well_file_pro(file_bytes, file_name)
        if error or not curves: return None, error
        
        if progress_callback: progress_callback(40)
        
        aligned_curves, common_len = align_curves(curves)
        if not aligned_curves: return None, "لا توجد بيانات صالحة بعد المعالجة"
        
        las = lasio.LASFile()
        las.well['WELL'] = lasio.HeaderItem('WELL', value=str(well_info['well_name']))
        
        if progress_callback: progress_callback(60)

        # 1. البحث عن منحنى العمق الحقيقي لإضافته كأول منحنى (مهم جداً)
        depth_name = None
        for col in aligned_curves.keys():
            if col.upper() in ['DEPT', 'DEPTH', 'TDEP', 'MD']:
                depth_name = col
                break
                
        if depth_name:
            depth_data = aligned_curves[depth_name]
            unit = metadata.get(depth_name, {}).get('unit', 'm')
            las.insert_curve(0, 'DEPT', depth_data, unit=unit, descr="Measured Depth")
        else:
            # فقط كحل أخير إذا لم يوجد عمق حقيقي
            fake_depth = np.arange(common_len) * 0.1524
            las.insert_curve(0, 'DEPT', fake_depth, unit="m", descr="Generated Depth (WARNING)")

        # 2. إضافة باقي المنحنيات مع وحداتها الحقيقية
        for name, data in aligned_curves.items():
            if name == depth_name: continue # تم إضافته بالفعل
            unit = metadata.get(name, {}).get('unit', '')
            desc = metadata.get(name, {}).get('desc', name)
            las.append_curve(name, data, unit=unit, descr=desc)
        
        output = io.StringIO()
        las.write(output, version=2)
        if progress_callback: progress_callback(100)
        
        return output.getvalue().encode('utf-8'), None
    except Exception as e:
        return None, str(e)


# ============================================================
# الرسوم البيانية
# ============================================================
def plot_log_data(data_dict, max_curves=5):
    if not data_dict: return None
    # محاولة العثور على منحنى العمق لاستخدامه في محور الصادات (Y)
    depth_name = next((c for c in data_dict.keys() if c.upper() in ['DEPT', 'DEPTH', 'TDEP']), None)
    
    # اختيار المنحنيات للرسم باستثناء العمق
    items = [(n, d) for n, d in data_dict.items() if len(d) > 10 and not np.isnan(d).all() and n != depth_name]
    items.sort(key=lambda x: len(x[1]), reverse=True)
    items = items[:max_curves]
    
    if not items: return None
    
    fig = make_subplots(rows=1, cols=len(items), subplot_titles=[n for n, _ in items], shared_yaxes=True, horizontal_spacing=0.03)
    
    for i, (name, data) in enumerate(items):
        if depth_name and len(data_dict[depth_name]) == len(data):
            y_axis = data_dict[depth_name]
            y_title = f"العمق ({depth_name})"
        else:
            y_axis = np.arange(len(data))
            y_title = "مؤشر النقطة (Index)"
            
        fig.add_trace(go.Scatter(x=data, y=y_axis, mode='lines', name=name, line=dict(width=1.5)), row=1, col=i+1)
        fig.update_xaxes(title_text="القيمة", row=1, col=i+1, zeroline=False)
        fig.update_yaxes(title_text=y_title if i == 0 else "", row=1, col=i+1, autorange='reversed')
        
    fig.update_layout(height=600, showlegend=False, template='plotly_white', margin=dict(l=50, r=20, t=80, b=50))
    return fig


# ============================================================
# واجهة المستخدم (UI)
# ============================================================
uploaded_files = st.file_uploader(
    "📂 اختر ملفات LIS أو DLIS",
    type=['lis', 'dlis', 'LIS', 'DLIS'],
    accept_multiple_files=True
)

if uploaded_files:
    st.markdown(f"### ✅ تم رفع {len(uploaded_files)} ملف")
    
    for file in uploaded_files:
        with st.expander(f"📄 عرض تفاصيل الملف: {file.name}"):
            file.seek(0)
            with st.spinner("جاري تحليل الهيدر والبيانات..."):
                curves, metadata, well_info, error = read_well_file_pro(file.read(), file.name)
                file.seek(0)
                
                if curves and not error:
                    st.success("✅ تمت قراءة الملف بنجاح واستخراج البنية المنطقية")
                    col1, col2, col3 = st.columns(3)
                    with col1: st.metric("🏷️ اسم البئر", well_info.get('well_name', 'غير معروف'))
                    with col2: st.metric("📊 عدد المنحنيات", well_info.get('total_curves', 0))
                    with col3: st.metric("🔧 تقنية القراءة", well_info.get('method', ''))
                    
                    fig = plot_log_data(curves)
                    if fig: st.plotly_chart(fig, use_container_width=True)
                    
                    with st.expander("📋 عرض تفاصيل المنحنيات والوحدات (Data Specs)"):
                        st.write("المنحنيات المستخرجة من الهيدر الأصلي:")
                        for name, data in curves.items():
                            unit = metadata.get(name, {}).get('unit', 'N/A')
                            desc = metadata.get(name, {}).get('desc', '')
                            st.write(f"🔹 **{name}**: {len(data)} points | Unit: `{unit}` | Desc: {desc}")
                else:
                    st.error(f"❌ {error}")
    
    st.markdown("---")
    col1, col2 = st.columns(2)
    with col1: compress = st.checkbox("📦 ضغط الملفات المحولة في ZIP", value=True)
    
    if st.button("🚀 تحويل إلى LAS (متوافق مع Techlog)", type="primary", use_container_width=True):
        st.markdown("### ⚡ جاري التحويل...")
        prog = st.progress(0)
        status = st.empty()
        converted, failed = [], []
        
        for i, file in enumerate(uploaded_files):
            status.text(f"جاري تحويل: {file.name} ({i+1}/{len(uploaded_files)})")
            
            def update(pct):
                overall = ((i) / len(uploaded_files)) * 100 + (pct / len(uploaded_files))
                prog.progress(min(100, int(overall)))
            
            file.seek(0)
            result, error = convert_to_las(file.read(), file.name, update)
            file.seek(0)
            
            if result:
                new_name = Path(file.name).stem + "_ProConverted.las"
                converted.append((new_name, result))
            else:
                failed.append((file.name, error))
                
        prog.progress(100)
        status.text("✅ تم الانتهاء!")
        
        col1, col2 = st.columns(2)
        with col1: st.success(f"✅ نجح تحويل: {len(converted)} ملف")
        with col2: 
            if failed: st.error(f"❌ فشل: {len(failed)} ملف")
            
        if failed:
            with st.expander("❌ عرض أسباب الفشل"):
                for name, error in failed: st.write(f"- **{name}**: {error}")
                
        if converted:
            if compress and len(converted) > 1:
                zbuf = io.BytesIO()
                with zipfile.ZipFile(zbuf, 'w', zipfile.ZIP_DEFLATED) as zf:
                    for name, data in converted:
                        zf.writestr(name, data)
                st.download_button(
                    label=f"📥 تحميل الكل كملف ZIP",
                    data=zbuf.getvalue(),
                    file_name=f"LAS_Converted_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip",
                    mime="application/zip",
                    use_container_width=True
                )
            else:
                for name, data in converted:
                    st.download_button(
                        label=f"📥 تحميل {name}",
                        data=data,
                        file_name=name,
                        mime="text/plain",
                        use_container_width=True
                    )
else:
    st.info("👆 ارفعي ملفاتك بصيغة LIS أو DLIS في الأعلى للبدء.")
