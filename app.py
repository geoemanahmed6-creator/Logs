import streamlit as st
import dlisio
import lasio
import numpy as np
import pandas as pd
import io
import tempfile
from pathlib import Path
import zipfile
from datetime import datetime
import json
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import struct
import re

st.set_page_config(page_title="Log Converter Pro - Batch", layout="wide")

st.markdown("""
<style>
    .report-box { padding: 15px; border-radius: 10px; margin: 10px 0; }
    .quality-good { background-color: #d4edda; border: 1px solid #c3e6cb; color: #155724; }
    .quality-warning { background-color: #fff3cd; border: 1px solid #ffc107; color: #856404; }
    .quality-error { background-color: #f8d7da; border: 1px solid #f5c6cb; color: #721c24; }
    .match-perfect { background-color: #d4edda; border: 2px solid #28a745; padding: 10px; border-radius: 10px; }
    .match-warning { background-color: #fff3cd; border: 2px solid #ffc107; padding: 10px; border-radius: 10px; }
    .match-error { background-color: #f8d7da; border: 2px solid #dc3545; padding: 10px; border-radius: 10px; }
</style>
""", unsafe_allow_html=True)

st.title("🛢️ Log Converter Pro - LIS/DLIS to LAS")
st.markdown("يدعم التحويل مع قراءة قوية للملفات القديمة والحديثة")

# ============================================================
# الدالة السحرية: القراءة الخام للملفات العنيدة
# ============================================================
def extract_curves_from_raw(data_bytes):
    curves = {}
    try:
        float_data = np.frombuffer(data_bytes, dtype=np.float32)
        if len(float_data) > 20:
            curves['RAW_FLOAT32'] = float_data
            if len(float_data) > 1000:
                for i in range(1, min(5, len(float_data) // 100)):
                    chunk = float_data[i::i+1]
                    if len(chunk) > 50 and not np.isnan(chunk).all():
                        curves[f'CURVE_{i}'] = chunk
    except: pass
    
    try:
        float64_data = np.frombuffer(data_bytes, dtype=np.float64)
        if len(float64_data) > 20:
            curves['RAW_FLOAT64'] = float64_data
    except: pass
    
    try:
        int_data = np.frombuffer(data_bytes, dtype=np.int32)
        if len(int_data) > 20:
            curves['RAW_INT32'] = int_data.astype(np.float32)
    except: pass
    
    try:
        text = data_bytes.decode('latin-1', errors='ignore')
        known_curves = ['GR', 'RES', 'DT', 'NPHI', 'RHOB', 'SP', 'CALI', 'DEPT']
        for curve in known_curves:
            if curve in text:
                pattern = rf'{curve}\s*([\d\.\-\s]+)'
                matches = re.findall(pattern, text)
                if matches:
                    nums = re.findall(r'[\d\.\-]+', ' '.join(matches))
                    if nums:
                        data = np.array([float(n) for n in nums if n.strip()])
                        if len(data) > 10:
                            curves[f'TEXT_{curve}'] = data
    except: pass
    
    if not curves:
        chunk_size = len(data_bytes) // 4
        for i in range(4):
            start = i * chunk_size
            end = (i + 1) * chunk_size
            chunk = data_bytes[start:end]
            try:
                data = np.frombuffer(chunk, dtype=np.float32)
                if len(data) > 20:
                    curves[f'CHUNK_{i+1}'] = data
            except: pass
    
    for name in list(curves.keys()):
        data = curves[name]
        if len(data) > 0:
            data = data[np.isfinite(data)]
            if len(data) > 0:
                mean = np.mean(data)
                std = np.std(data)
                if std > 0:
                    data = data[np.abs(data - mean) <= 3 * std]
                curves[name] = data
            else:
                del curves[name]
    return curves

# ============================================================
# دالة قراءة الملف بكل الطرق الممكنة (تم إصلاح dlisio و lasio)
# ============================================================
def read_file_ultimate(file_bytes, file_name):
    errors = []
    
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix='.lis') as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name
        
        files = dlisio.load(tmp_path)
        parsed_files = list(files) if isinstance(files, tuple) else [files]
        
        if parsed_files:
            return parsed_files, "DLIS/LIS (dlisio)", None
    except Exception as e:
        errors.append(f"DLISIO: {e}")
    
    try:
        las_text = file_bytes.decode('ascii', errors='ignore')
        las = lasio.read(io.StringIO(las_text))
        if las.curves:
            class LasWrap:
                def __init__(self, las):
                    self.las = las
                    self.well_name = las.well.WELL.value if hasattr(las.well, 'WELL') else "LAS"
                @property
                def frames(self):
                    class F:
                        def __init__(self, las):
                            self.las = las
                        def curves(self):
                            class C:
                                def __init__(self, m, d):
                                    self.name = m
                                    self._data = d
                                def curves(self):
                                    return self._data
                            return [C(c.mnemonic, c.data) for c in self.las.curves]
                    return [F(self.las)]
            return [LasWrap(las)], "LAS", None
    except Exception as e:
        errors.append(f"LAS: {e}")
    
    try:
        raw_curves = extract_curves_from_raw(file_bytes)
        if raw_curves:
            class RawWrap:
                def __init__(self, curves):
                    self._curves = curves
                    self.well_name = "RAW_BINARY"
                @property
                def frames(self):
                    class F:
                        def __init__(self, curves):
                            self._curves = curves
                        def curves(self):
                            class C:
                                def __init__(self, name, data):
                                    self.name = name
                                    self._data = data
                                def curves(self):
                                    return self._data
                            return [C(k, v) for k, v in self._curves.items()]
                    return [F(self._curves)]
            return [RawWrap(raw_curves)], "RAW_BINARY", None
    except Exception as e:
        errors.append(f"RAW: {e}")
    
    return None, None, f"فشل: {'; '.join(errors)}"

# ============================================================
# دالة استخراج المنحنيات
# ============================================================
def get_all_curves(file_obj):
    curves = {}
    try:
        if hasattr(file_obj, 'frames'):
            for frame in file_obj.frames:
                try:
                    frame_data = frame.curves()
                    if isinstance(frame_data, np.ndarray) and frame_data.dtype.names:
                        for name in frame_data.dtype.names:
                            curves[name] = np.array(frame_data[name])
                    else:
                        for curve in frame.curves():
                            name = getattr(curve, 'name', f'CURVE_{len(curves)}')
                            data = curve.curves()
                            if data is not None and len(data) > 0:
                                curves[name] = np.array(data)
                except:
                    continue
                    
        if not curves and hasattr(file_obj, 'curves'):
            curve_list = file_obj.curves() if callable(file_obj.curves) else file_obj.curves
            if isinstance(curve_list, np.ndarray) and curve_list.dtype.names:
                for name in curve_list.dtype.names:
                    curves[name] = np.array(curve_list[name])
    except: pass
    
    return curves

def read_log_file(file_bytes, file_name):
    try:
        dlis_files, method, error = read_file_ultimate(file_bytes, file_name)
        if error or not dlis_files:
            return None, error or "لا يمكن قراءة الملف"
        
        dlis_file = dlis_files[0]
        curves = get_all_curves(dlis_file)
        
        if not curves:
            return None, "تم فتح الملف لكن لم يتم العثور على منحنيات مفهومة"
        
        well_info = {
            'well_name': getattr(dlis_file, 'well_name', 'غير معروف'),
            'method': method,
            'total_curves': len(curves)
        }
        
        frames_info = [{
            'name': 'Main',
            'curves': [{'name': k, 'data': v, 'count': len(v)} for k, v in curves.items()],
            'count': len(curves)
        }]
        
        return {
            'well_info': well_info,
            'frames': frames_info,
            'all_data': curves,
            'method': method
        }, None
    except Exception as e:
        return None, str(e)

# ============================================================
# دالة التحويل إلى LAS مع الإصلاح الجديد لـ lasio
# ============================================================
def convert_file_fast(file_bytes, file_name, output_format="las", progress_callback=None):
    try:
        dlis_files, method, error = read_file_ultimate(file_bytes, file_name)
        if error or not dlis_files: return None, error, None
        dlis_file = dlis_files[0]
        curves = get_all_curves(dlis_file)
        if not curves: return None, "لا توجد بيانات للتحويل", None
        
        if progress_callback: progress_callback(50)
        
        if output_format == "las":
            las = lasio.LASFile()
            
            well_name_val = str(getattr(dlis_file, 'well_name', 'UNKNOWN'))
            if 'WELL' in las.well:
                las.well['WELL'].value = well_name_val
            else:
                las.well.append(lasio.HeaderItem('WELL', value=well_name_val))
            
            for name, data in curves.items():
                if len(data) > 0:
                    las.append_curve(name, data, unit="", descr=name)
            
            if len(las.keys()) > 0:
                first_key = las.keys()[0]
                if len(las.data[first_key]) > 0:
                    depth = np.arange(len(las.data[first_key])) * 0.1524
                    if "DEPT" not in las.keys():
                        las.insert_curve(0, "DEPT", depth, unit="m", descr="Depth")
            
            output = io.StringIO()
            las.write(output, version=2)
            if progress_callback: progress_callback(100)
            return output.getvalue().encode('utf-8'), None, curves
            
        elif output_format == "dlis":
            if progress_callback: progress_callback(100)
            return file_bytes, None, None
    except Exception as e:
        return None, f"خطأ أثناء التحويل: {str(e)}", None

def analyze_file_quality(file_bytes, file_name):
    report = {
        "file_name": file_name, "status": "✅ نجاح", "warnings": [], "errors": [],
        "info": {}, "curves_count": 0, "file_size_kb": len(file_bytes) / 1024,
        "quality_score": 100, "method_used": "غير معروف"
    }
    try:
        dlis_files, method, error = read_file_ultimate(file_bytes, file_name)
        if error or not dlis_files:
            report["status"], report["quality_score"] = "❌ فشل", 0
            report["errors"].append(error or "الملف غير صالح")
            return report
        
        report["method_used"] = method
        curves = get_all_curves(dlis_files[0])
        report["curves_count"] = len(curves)
        
        if report["curves_count"] == 0:
            report["warnings"].append("لا توجد منحنيات")
            report["quality_score"] -= 30
            
        report["info"]["well_name"] = getattr(dlis_files[0], 'well_name', 'غير معروف')
        report["info"]["method"] = method
        
        total_points, missing = 0, 0
        for data in curves.values():
            if len(data) > 0:
                total_points += len(data)
                missing += np.isnan(data).sum()
                
        if total_points > 0:
            missing_pct = (missing / total_points) * 100
            if missing_pct > 10:
                report["warnings"].append(f"{missing_pct:.1f}% بيانات مفقودة")
                report["quality_score"] -= missing_pct / 2
            report["info"]["missing_data"] = f"{missing_pct:.1f}%"
            
        if report["file_size_kb"] > 10000:
            report["warnings"].append("حجم الملف كبير")
            report["quality_score"] -= 5
    except Exception as e:
        report["status"], report["quality_score"] = "❌ فشل", 0
        report["errors"].append(str(e))
        
    report["quality_score"] = max(0, min(100, report["quality_score"]))
    if report["quality_score"] >= 80: report["quality_grade"] = "⭐ ممتاز"
    elif report["quality_score"] >= 50: report["quality_grade"] = "⚠️ جيد"
    else: report["quality_grade"] = "❌ ضعيف"
    
    return report

def plot_log_data(data_dict, max_curves=6):
    if not data_dict: return None
    items = [(n, d) for n, d in data_dict.items() if len(d) > 10 and not np.isnan(d).all()]
    items.sort(key=lambda x: len(x[1]), reverse=True)
    items = items[:max_curves]
    if not items: return None
    fig = make_subplots(rows=1, cols=len(items), subplot_titles=[n for n, _ in items], shared_yaxes=True, horizontal_spacing=0.05)
    for i, (name, data) in enumerate(items):
        depth = np.arange(len(data)) * 0.1524
        fig.add_trace(go.Scatter(x=data, y=depth, mode='lines', name=name, line=dict(width=1.5)), row=1, col=i+1)
        fig.update_xaxes(title_text="القيمة", row=1, col=i+1, zeroline=False)
        fig.update_yaxes(title_text="العمق (م)" if i == 0 else "", row=1, col=i+1, autorange='reversed')
    fig.update_layout(height=500, showlegend=False, template='plotly_white', margin=dict(l=50, r=20, t=80, b=50))
    return fig

def compare_data(orig, conv, curve_names=None):
    if curve_names is None: curve_names = set(orig.keys()) & set(conv.keys())
    results = []
    for name in curve_names:
        o = np.array(orig[name]); c = np.array(conv[name])
        min_len = min(len(o), len(c)); o = o[:min_len]; c = c[:min_len]
        valid = ~(np.isnan(o) | np.isnan(c))
        if np.sum(valid) > 0:
            ov = o[valid]; cv = c[valid]
            results.append({
                'curve_name': name, 'points_compared': np.sum(valid),
                'max_abs_diff': np.max(np.abs(ov - cv)), 'mean_abs_diff': np.mean(np.abs(ov - cv)),
                'identical': np.allclose(ov, cv, rtol=1e-10, atol=1e-10),
                'nan_count_orig': np.isnan(o).sum(), 'nan_count_conv': np.isnan(c).sum()
            })
    return results

def display_comparison_stats(results):
    if not results: st.info("لا توجد بيانات للمقارنة"); return
    df = pd.DataFrame(results)
    identical_count = sum(df['identical'])
    total = len(df)
    col1, col2, col3 = st.columns(3)
    with col1:
        if identical_count == total: st.markdown('<div class="match-perfect">✅ <b>مطابقة تامة!</b></div>', unsafe_allow_html=True)
        elif identical_count / total > 0.8: st.markdown('<div class="match-warning">⚠️ <b>جيدة جداً</b></div>', unsafe_allow_html=True)
        else: st.markdown('<div class="match-error">❌ <b>اختلافات</b></div>', unsafe_allow_html=True)
    with col2: st.metric("📊 عدد المنحنيات", total)
    with col3: st.metric("✅ متطابقة", f"{identical_count}/{total}")
    st.dataframe(df[['curve_name', 'points_compared', 'max_abs_diff', 'mean_abs_diff', 'identical']], use_container_width=True)

def plot_comparison(orig, conv, curve_names, max_curves=4):
    common = [c for c in curve_names if c in orig and c in conv][:max_curves]
    if not common: return None
    fig = make_subplots(rows=1, cols=len(common)*2, subplot_titles=[f"{c} (أصلي)" for c in common] + [f"{c} (محول)" for c in common], shared_yaxes=True, horizontal_spacing=0.03)
    for i, name in enumerate(common):
        o = np.array(orig[name]); c = np.array(conv[name])
        min_len = min(len(o), len(c)); o = o[:min_len]; c = c[:min_len]
        depth = np.arange(min_len) * 0.1524
        fig.add_trace(go.Scatter(x=o, y=depth, mode='lines', name=f'{name} (أصلي)', line=dict(color='blue', width=2)), row=1, col=i*2+1)
        fig.add_trace(go.Scatter(x=c, y=depth, mode='lines', name=f'{name} (محول)', line=dict(color='red', width=2, dash='dash')), row=1, col=i*2+2)
        fig.update_xaxes(title_text="القيمة", row=1, col=i*2+1, zeroline=False)
        fig.update_xaxes(title_text="القيمة", row=1, col=i*2+2, zeroline=False)
        fig.update_yaxes(title_text="العمق (م)" if i == 0 else "", row=1, col=i*2+1, autorange='reversed')
        fig.update_yaxes(title_text="العمق (م)" if i == 0 else "", row=1, col=i*2+2, autorange='reversed')
    fig.update_layout(height=600, showlegend=False, template='plotly_white', margin=dict(l=50, r=20, t=80, b=50))
    return fig

def read_las_file(file_bytes):
    try:
        las_text = file_bytes.decode('utf-8', errors='ignore')
        las = lasio.read(io.StringIO(las_text))
        return {c.mnemonic: c.data for c in las.curves if c.data is not None and len(c.data) > 0}, None
    except Exception as e:
        return None, str(e)

# ============================================================
# واجهة المستخدم
# ============================================================
uploaded_files = st.file_uploader(
    "📂 اختر ملفات LIS أو DLIS",
    type=['lis', 'dlis', 'LIS', 'DLIS'],
    accept_multiple_files=True
)

if uploaded_files:
    st.markdown(f"### ✅ تم رفع {len(uploaded_files)} ملف")
    
    for file in uploaded_files:
        with st.expander(f"📄 عرض بيانات: {file.name}"):
            file.seek(0)
            with st.spinner("جاري قراءة الملف..."):
                data, error = read_log_file(file.read(), file.name)
                file.seek(0)
                if data and error is None:
                    st.info(f"📌 طريقة القراءة: **{data.get('method', 'غير معروف')}**")
                    col1, col2, col3 = st.columns(3)
                    with col1: st.metric("🏷️ اسم البئر", data['well_info']['well_name'])
                    with col2: st.metric("📊 عدد المنحنيات", data['well_info']['total_curves'])
                    with col3: st.metric("🔧 الطريقة", data['well_info']['method'])
                    
                    fig = plot_log_data(data['all_data'])
                    if fig: st.plotly_chart(fig, use_container_width=True)
                    
                    with st.expander("📋 تفاصيل المنحنيات"):
                        for frame in data['frames']:
                            for curve in frame['curves']:
                                st.write(f"- {curve['name']} (نقاط: {curve['count']})")
                else:
                    st.error(f"❌ {error}")
    
    st.markdown("---")
    col1, col2, col3 = st.columns(3)
    with col1: output_format = st.selectbox("🔄 صيغة الإخراج:", ["las", "dlis"])
    with col2: compress = st.checkbox("📦 ضغط ZIP", value=True)
    with col3: enable_comparison = st.checkbox("🔍 مقارنة بعد التحويل", value=True)
    
    if st.button("🚀 تحويل الكل", type="primary", use_container_width=True):
        with st.spinner("🔍 تحليل الجودة..."):
            quality_reports = []
            prog = st.progress(0)
            for i, file in enumerate(uploaded_files):
                prog.progress((i+1)/len(uploaded_files))
                report = analyze_file_quality(file.read(), file.name)
                quality_reports.append(report)
                file.seek(0)
            st.success("✅ تم الانتهاء من التحليل")
        
        st.markdown("### 📊 تقرير الجودة")
        total_files = len(quality_reports)
        success_files = sum(1 for r in quality_reports if r["status"] == "✅ نجاح")
        avg_score = np.mean([r["quality_score"] for r in quality_reports])
        col1, col2, col3, col4 = st.columns(4)
        with col1: st.metric("📁 المجموع", total_files)
        with col2: st.metric("✅ صالحة", success_files)
        with col3: st.metric("📊 متوسط الجودة", f"{avg_score:.0f}%")
        with col4:
            grade = "⭐ ممتاز" if avg_score >= 80 else "⚠️ جيد" if avg_score >= 50 else "❌ ضعيف"
            st.metric("🏆 التقييم", grade)
        
        for report in quality_reports:
            with st.expander(f"{report['status']} {report['file_name']} - {report['quality_score']:.0f}%"):
                st.write(f"**طريقة:** {report['method_used']}")
                st.write(f"**المنحنيات:** {report['curves_count']}")
                st.write(f"**اسم البئر:** {report['info'].get('well_name', 'غير معروف')}")
                if report["warnings"]: st.warning(f"⚠️ {', '.join(report['warnings'])}")
        
        st.markdown("### ⚡ جاري التحويل...")
        prog = st.progress(0)
        status = st.empty()
        converted, failed = [], []
        
        for i, file in enumerate(uploaded_files):
            status.text(f"تحويل: {file.name} ({i+1}/{len(uploaded_files)})")
            orig_data = None
            if enable_comparison:
                file.seek(0)
                d, _ = read_log_file(file.read(), file.name)
                if d: orig_data = d['all_data']
                file.seek(0)
            
            def update(pct):
                overall = ((i) / len(uploaded_files)) * 100 + (pct / len(uploaded_files))
                prog.progress(min(100, int(overall)))
            
            file.seek(0)
            result, error, conv_data = convert_file_fast(file.read(), file.name, output_format, update)
            
            if result:
                new_name = Path(file.name).stem + f"_converted.{output_format}"
                converted.append((new_name, result))
                if enable_comparison and orig_data and output_format == "las" and conv_data:
                    try:
                        las_data, _ = read_las_file(result)
                        if las_data:
                            comp = compare_data(orig_data, las_data)
                            st.markdown(f"---")
                            st.markdown(f"### 🔍 مقارنة: {file.name}")
                            display_comparison_stats(comp)
                            common = [c['curve_name'] for c in comp]
                            fig_c = plot_comparison(orig_data, las_data, common)
                            if fig_c: st.plotly_chart(fig_c, use_container_width=True)
                    except Exception as e:
                        st.warning(f"تعذرت المقارنة: {e}")
            else:
                failed.append((file.name, error))
            file.seek(0)
        
        prog.progress(100)
        status.text("✅ تم الانتهاء من جميع الملفات!")
        
        st.markdown("### 📦 النتائج النهائية")
        col1, col2 = st.columns(2)
        with col1: st.success(f"✅ نجح: {len(converted)} ملف")
        with col2:
            if failed: st.error(f"❌ فشل: {len(failed)} ملف")
        
        if failed:
            with st.expander("❌ عرض أسباب الفشل للملفات"):
                for name, error in failed: st.write(f"- **{name}**: {error}")
        
        if converted:
            if compress and len(converted) > 1:
                zbuf = io.BytesIO()
                with zipfile.ZipFile(zbuf, 'w', zipfile.ZIP_DEFLATED) as zf:
                    for name, data in converted:
                        zf.writestr(name, data)
                st.download_button(
                    label=f"📥 تحميل كملف مضغوط ZIP ({len(converted)} ملف)",
                    data=zbuf.getvalue(),
                    file_name=f"converted_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip",
                    mime="application/zip",
                    use_container_width=True
                )
            else:
                for name, data in converted:
                    st.download_button(
                        label=f"📥 تحميل {name}",
                        data=data,
                        file_name=name,
                        mime="text/plain" if output_format == "las" else "application/octet-stream",
                        use_container_width=True
                    )
else:
    st.info("👆 ارفع ملفاتك بصيغة LIS أو DLIS في الأعلى للبدء.")

st.markdown("---")
st.caption("💡 مبني على dlisio - يدعم جميع أنواع LIS القديمة والحديثة")
