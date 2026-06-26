import streamlit as st
import dlisio
import lasio
import numpy as np
import pandas as pd
import io
import tempfile
from pathlib import Path
import zipfile
import time
from datetime import datetime
import json
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import struct

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

st.title("🛢️ Log Converter Pro - مع المقارنة")
st.markdown("قم بتحويل ملفات LIS و DLIS إلى LAS أو DLIS مع مقارنة البيانات قبل وبعد التحويل")

# ==============================================
# دالة مساعدة لاستخراج المنحنيات بأمان
# ==============================================

def safe_get_curves(dlis_file):
    """
    محاولة استخراج المنحنيات من ملف LIS/DLIS بغض النظر عن البنية الداخلية
    """
    curves_data = {}
    frames_info = []
    
    # المحاولة الأولى: استخدام frames (للـ DLIS الحديث)
    try:
        if hasattr(dlis_file, 'frames'):
            for frame in dlis_file.frames:
                frame_name = getattr(frame, 'name', 'Frame')
                frame_curves = []
                for curve in frame.curves():
                    try:
                        data = curve.curves()
                        if data is not None and len(data) > 0:
                            name = getattr(curve, 'name', f'curve_{len(curves_data)}')
                            curves_data[name] = data
                            frame_curves.append({'name': name, 'data': data, 'count': len(data)})
                    except:
                        continue
                if frame_curves:
                    frames_info.append({'name': frame_name, 'curves': frame_curves, 'count': len(frame_curves)})
        else:
            raise AttributeError("No 'frames' attribute")
    except Exception as e1:
        # المحاولة الثانية: استخدام objects (للـ LIS القديم)
        try:
            if hasattr(dlis_file, 'objects'):
                for obj in dlis_file.objects:
                    # البحث عن الكائنات التي تحتوي على منحنيات
                    if hasattr(obj, 'curves'):
                        for curve in obj.curves():
                            try:
                                data = curve.curves()
                                if data is not None and len(data) > 0:
                                    name = getattr(curve, 'name', f'curve_{len(curves_data)}')
                                    curves_data[name] = data
                            except:
                                continue
                    elif hasattr(obj, 'data'):
                        # بعض الكائنات تخزن البيانات مباشرة
                        try:
                            data = obj.data
                            if data is not None and len(data) > 0:
                                name = getattr(obj, 'name', f'obj_{len(curves_data)}')
                                curves_data[name] = data
                        except:
                            continue
                if curves_data:
                    frames_info.append({'name': 'Imported', 'curves': [{'name': k, 'data': v, 'count': len(v)} for k, v in curves_data.items()], 'count': len(curves_data)})
            else:
                raise AttributeError("No 'objects' attribute")
        except Exception as e2:
            # المحاولة الثالثة: البحث عن أي بيانات رقمية في الكائن
            try:
                for attr_name in dir(dlis_file):
                    if attr_name.startswith('_'):
                        continue
                    attr = getattr(dlis_file, attr_name)
                    if isinstance(attr, (np.ndarray, list)) and len(attr) > 10:
                        curves_data[attr_name] = np.array(attr)
                if curves_data:
                    frames_info.append({'name': 'AutoDetect', 'curves': [{'name': k, 'data': v, 'count': len(v)} for k, v in curves_data.items()], 'count': len(curves_data)})
            except:
                pass
    
    return curves_data, frames_info


# ==============================================
# دوال قراءة الملفات بطرق متعددة
# ==============================================

def read_file_with_fallback(file_bytes, file_name):
    """محاولة قراءة الملف بأكثر من طريقة"""
    errors = []
    
    # الطريقة 1: DLIS
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix='.dlis') as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name
        with dlisio.dlis.load(tmp_path) as dlis_files:
            if dlis_files:
                return dlis_files, "DLIS", None
    except Exception as e:
        errors.append(f"DLIS: {str(e)}")
    finally:
        try: Path(tmp_path).unlink()
        except: pass
    
    # الطريقة 2: LIS
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix='.lis') as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name
        with dlisio.lis.load(tmp_path) as lis_files:
            if lis_files:
                return lis_files, "LIS", None
    except Exception as e:
        errors.append(f"LIS: {str(e)}")
    finally:
        try: Path(tmp_path).unlink()
        except: pass
    
    # الطريقة 3: محاولة كـ LAS
    try:
        las = lasio.read(io.BytesIO(file_bytes))
        if las.curves:
            class LasWrapper:
                def __init__(self, las):
                    self.las = las
                    self.well_name = las.well.WELL.value if hasattr(las.well, 'WELL') else "LAS_FILE"
                def curves(self):
                    return [(c.mnemonic, c.data) for c in self.las.curves]
            return [LasWrapper(las)], "LAS", None
    except Exception as e:
        errors.append(f"LAS: {str(e)}")
    
    # الطريقة 4: قراءة خام (Binary)
    try:
        data = np.frombuffer(file_bytes, dtype=np.float32)
        if len(data) > 10:
            class RawWrapper:
                def __init__(self, data):
                    self.data = data
                    self.well_name = "RAW_BINARY"
                def curves(self):
                    return [("RAW_DATA", self.data)]
            return [RawWrapper(data)], "RAW_BINARY", None
    except Exception as e:
        errors.append(f"RAW: {str(e)}")
    
    return None, None, f"فشل بكل الطرق: {'; '.join(errors)}"


def read_log_file(file_bytes, file_name):
    """قراءة ملف الوج باستخدام safe_get_curves"""
    try:
        dlis_files, method, error = read_file_with_fallback(file_bytes, file_name)
        if error or not dlis_files:
            return None, error or "لا يمكن قراءة الملف"
        
        dlis_file = dlis_files[0]
        
        # استخراج المنحنيات باستخدام الدالة المساعدة
        all_data, frames_info = safe_get_curves(dlis_file)
        
        if not all_data:
            return None, "لا توجد منحنيات في الملف"
        
        well_info = {
            'well_name': getattr(dlis_file, 'well_name', 'غير معروف'),
            'field_name': getattr(dlis_file, 'field_name', 'غير معروف'),
            'total_curves': len(all_data),
            'total_frames': len(frames_info),
            'method': method
        }
        
        return {
            'well_info': well_info,
            'frames': frames_info,
            'all_data': all_data,
            'file_name': file_name,
            'method': method
        }, None
        
    except Exception as e:
        return None, str(e)


def convert_file_fast(file_bytes, file_name, output_format="las", progress_callback=None):
    """تحويل سريع مع دعم التقدم"""
    try:
        dlis_files, method, error = read_file_with_fallback(file_bytes, file_name)
        if error or not dlis_files:
            return None, error or "لا يمكن قراءة الملف", None
        
        dlis_file = dlis_files[0]
        if progress_callback:
            progress_callback(50)
        
        # استخراج البيانات باستخدام safe_get_curves
        all_data, frames_info = safe_get_curves(dlis_file)
        
        if not all_data:
            return None, "لا توجد بيانات قابلة للقراءة", None
        
        if output_format == "las":
            las = lasio.LASFile()
            las.well = lasio.WellItem("WELL", value=getattr(dlis_file, 'well_name', 'UNKNOWN'))
            
            for curve_name, data in all_data.items():
                if len(data) > 0:
                    las.append_curve(curve_name, data, unit="", descr=curve_name)
            
            if len(las.keys()) > 0:
                first_key = las.keys()[0]
                if len(las.data[first_key]) > 0:
                    depth = np.arange(len(las.data[first_key])) * 0.1524
                    las.insert_curve(0, "DEPT", depth, unit="m", descr="Depth")
            
            output = io.StringIO()
            las.write(output, version=2)
            
            if progress_callback:
                progress_callback(100)
            
            return output.getvalue().encode('utf-8'), None, all_data
        
        elif output_format == "dlis":
            if progress_callback:
                progress_callback(100)
            return file_bytes, None, None
    
    except Exception as e:
        return None, str(e), None


def analyze_file_quality(file_bytes, file_name):
    """تحليل جودة الملف مع safe_get_curves"""
    report = {
        "file_name": file_name,
        "status": "✅ نجاح",
        "warnings": [],
        "errors": [],
        "info": {},
        "curves_count": 0,
        "depth_range": None,
        "file_size_kb": len(file_bytes) / 1024,
        "quality_score": 100,
        "method_used": "غير معروف"
    }
    
    try:
        dlis_files, method, error = read_file_with_fallback(file_bytes, file_name)
        if error or not dlis_files:
            report["status"] = "❌ فشل"
            report["errors"].append(error or "الملف غير صالح")
            report["quality_score"] = 0
            return report
        
        report["method_used"] = method
        dlis_file = dlis_files[0]
        
        all_data, frames_info = safe_get_curves(dlis_file)
        report["curves_count"] = len(all_data)
        
        if report["curves_count"] == 0:
            report["warnings"].append("لا توجد منحنيات")
            report["quality_score"] -= 30
        
        report["info"]["well_name"] = getattr(dlis_file, 'well_name', 'غير معروف')
        report["info"]["field_name"] = getattr(dlis_file, 'field_name', 'غير معروف')
        report["info"]["method"] = method
        
        # حساب البيانات المفقودة
        total_points = 0
        missing_data = 0
        for data in all_data.values():
            if len(data) > 0:
                total_points += len(data)
                missing_data += np.isnan(data).sum()
        
        if total_points > 0:
            missing_percent = (missing_data / total_points) * 100
            if missing_percent > 10:
                report["warnings"].append(f"{missing_percent:.1f}% بيانات مفقودة")
                report["quality_score"] -= missing_percent / 2
            report["info"]["missing_data_percent"] = f"{missing_percent:.1f}%"
        
        if report["file_size_kb"] > 10000:
            report["warnings"].append("حجم الملف كبير")
            report["quality_score"] -= 5
        
    except Exception as e:
        report["status"] = "❌ فشل"
        report["errors"].append(str(e))
        report["quality_score"] = 0
    
    report["quality_score"] = max(0, min(100, report["quality_score"]))
    if report["quality_score"] >= 80:
        report["quality_grade"] = "⭐ ممتاز"
    elif report["quality_score"] >= 50:
        report["quality_grade"] = "⚠️ جيد"
    else:
        report["quality_grade"] = "❌ ضعيف"
    
    return report


# ==============================================
# دوال الرسوم البيانية والمقارنة (مختصرة)
# ==============================================

def plot_log_data(data_dict, max_curves=6):
    if not data_dict:
        return None
    curves_to_plot = [(name, data) for name, data in data_dict.items() if len(data) > 10 and not np.isnan(data).all()]
    curves_to_plot.sort(key=lambda x: len(x[1]), reverse=True)
    curves_to_plot = curves_to_plot[:max_curves]
    if not curves_to_plot:
        return None
    n = len(curves_to_plot)
    fig = make_subplots(rows=1, cols=n, subplot_titles=[name for name, _ in curves_to_plot], shared_yaxes=True, horizontal_spacing=0.05)
    for i, (name, data) in enumerate(curves_to_plot):
        depth = np.arange(len(data)) * 0.1524
        fig.add_trace(go.Scatter(x=data, y=depth, mode='lines', name=name, line=dict(width=1.5), hovertemplate=f'<b>{name}</b><br>القيمة: %{{x:.2f}}<br>العمق: %{{y:.2f}} م<extra></extra>'), row=1, col=i+1)
        fig.update_xaxes(title_text="القيمة", row=1, col=i+1, zeroline=False, gridcolor='lightgray')
        fig.update_yaxes(title_text="العمق (م)" if i == 0 else "", row=1, col=i+1, autorange='reversed', gridcolor='lightgray')
    fig.update_layout(height=500, showlegend=False, template='plotly_white', margin=dict(l=50, r=20, t=80, b=50), hovermode='y unified')
    return fig


def compare_data(orig, conv, curve_names=None):
    if curve_names is None:
        curve_names = set(orig.keys()) & set(conv.keys())
    results = []
    for name in curve_names:
        o = np.array(orig[name])
        c = np.array(conv[name])
        min_len = min(len(o), len(c))
        o = o[:min_len]; c = c[:min_len]
        valid = ~(np.isnan(o) | np.isnan(c))
        if np.sum(valid) > 0:
            ov = o[valid]; cv = c[valid]
            diff = ov - cv
            results.append({
                'curve_name': name,
                'points_compared': np.sum(valid),
                'max_abs_diff': np.max(np.abs(diff)),
                'mean_abs_diff': np.mean(np.abs(diff)),
                'identical': np.allclose(ov, cv, rtol=1e-10, atol=1e-10),
                'nan_count_orig': np.isnan(o).sum(),
                'nan_count_conv': np.isnan(c).sum()
            })
    return results


def display_comparison_stats(comparison_results):
    if not comparison_results:
        st.info("لا توجد بيانات للمقارنة"); return
    df = pd.DataFrame(comparison_results)
    identical_count = sum(df['identical'])
    total = len(df)
    col1, col2, col3 = st.columns(3)
    with col1:
        if identical_count == total:
            st.markdown('<div class="match-perfect">✅ <b>مطابقة تامة!</b><br>جميع المنحنيات متطابقة 100%</div>', unsafe_allow_html=True)
        elif identical_count / total > 0.8:
            st.markdown('<div class="match-warning">⚠️ <b>مطابقة جيدة جداً</b><br>معظم المنحنيات متطابقة</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="match-error">❌ <b>اختلافات ملحوظة!</b><br>راجع البيانات</div>', unsafe_allow_html=True)
    with col2:
        st.metric("📊 عدد المنحنيات", total)
    with col3:
        st.metric("✅ متطابقة", f"{identical_count}/{total}")
    st.dataframe(df[['curve_name', 'points_compared', 'max_abs_diff', 'mean_abs_diff', 'identical']], use_container_width=True)


def plot_comparison(orig, conv, curve_names, max_curves=4):
    common = [c for c in curve_names if c in orig and c in conv][:max_curves]
    if not common:
        return None
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
    fig.update_layout(height=600, showlegend=False, template='plotly_white', margin=dict(l=50, r=20, t=80, b=50), hovermode='y unified')
    return fig


# ==============================================
# واجهة المستخدم
# ==============================================

uploaded_files = st.file_uploader(
    "📂 اختر ملفات LIS أو DLIS",
    type=['lis', 'dlis', 'LIS', 'DLIS', 'las', 'LAS'],
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
                    st.info(f"📌 تمت القراءة باستخدام: **{data.get('method', 'غير معروف')}**")
                    col1, col2, col3, col4 = st.columns(4)
                    with col1: st.metric("🏷️ اسم البئر", data['well_info']['well_name'])
                    with col2: st.metric("📊 عدد المنحنيات", data['well_info']['total_curves'])
                    with col3: st.metric("📁 عدد الأطر", data['well_info']['total_frames'])
                    with col4: st.metric("🔧 الطريقة", data['well_info']['method'])
                    
                    st.markdown("#### 📈 الرسوم البيانية")
                    fig = plot_log_data(data['all_data'])
                    if fig: st.plotly_chart(fig, use_container_width=True)
                    else: st.warning("لا توجد بيانات كافية للرسم")
                    
                    with st.expander("📋 عرض المنحنيات"):
                        for frame in data['frames']:
                            st.markdown(f"**{frame['name']}** ({frame['count']} منحنيات)")
                            for curve in frame['curves']:
                                st.write(f"- {curve['name']} (نقاط: {curve['count']})")
                else:
                    st.error(f"❌ خطأ: {error}")
                    st.warning("💡 تأكد أن الملف بصيغة LIS أو DLIS صالحة. بعض الملفات تحتاج برامج متخصصة.")
    
    st.markdown("---")
    col1, col2, col3 = st.columns(3)
    with col1:
        output_format = st.selectbox("🔄 صيغة الإخراج:", ["las", "dlis"], format_func=lambda x: "LAS (نصي)" if x == "las" else "DLIS (ثنائي)")
    with col2:
        compress = st.checkbox("📦 ضغط ZIP", value=True)
    with col3:
        enable_comparison = st.checkbox("🔍 تمكين المقارنة", value=True)
    
    if st.button("🚀 تحويل الكل", type="primary", use_container_width=True):
        with st.spinner("🔍 جاري تحليل الجودة..."):
            quality_reports = []
            progress_bar = st.progress(0)
            for i, file in enumerate(uploaded_files):
                progress_bar.progress((i+1)/len(uploaded_files))
                report = analyze_file_quality(file.read(), file.name)
                quality_reports.append(report)
                file.seek(0)
            st.success("✅ تم تحليل الجودة")
        
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
            with st.expander(f"{report['status']} {report['file_name']} - {report['quality_score']:.0f}% ({report['quality_grade']})"):
                st.write(f"**طريقة القراءة:** {report['method_used']}")
                st.write(f"**عدد المنحنيات:** {report['curves_count']}")
                st.write(f"**الحجم:** {report['file_size_kb']:.1f} KB")
                st.write(f"**اسم البئر:** {report['info'].get('well_name', 'غير معروف')}")
                if report["warnings"]:
                    st.warning(f"⚠️ {', '.join(report['warnings'])}")
                if report["errors"]:
                    st.error(f"❌ {', '.join(report['errors'])}")
        
        st.markdown("### ⚡ جاري التحويل...")
        progress_bar = st.progress(0)
        status_text = st.empty()
        converted_files = []
        failed_files = []
        all_comparisons = []
        
        for i, file in enumerate(uploaded_files):
            status_text.text(f"جاري تحويل: {file.name} ({i+1}/{len(uploaded_files)})")
            original_data = None
            if enable_comparison:
                file.seek(0)
                data, _ = read_log_file(file.read(), file.name)
                if data:
                    original_data = data['all_data']
                file.seek(0)
            
            def update_progress(pct):
                overall = ((i) / len(uploaded_files)) * 100 + (pct / len(uploaded_files))
                progress_bar.progress(min(100, int(overall)))
            
            file.seek(0)
            result, error, converted_data = convert_file_fast(file.read(), file.name, output_format, update_progress)
            
            if result:
                new_filename = Path(file.name).stem + f"_converted.{output_format}"
                converted_files.append((new_filename, result))
                if enable_comparison and original_data and output_format == "las" and converted_data:
                    try:
                        las_data, _ = read_las_file(result)
                        if las_data:
                            comparison = compare_data(original_data, las_data)
                            all_comparisons.append({'file_name': file.name, 'comparison': comparison})
                            st.markdown(f"---")
                            st.markdown(f"### 🔍 مقارنة: {file.name}")
                            display_comparison_stats(comparison)
                            common_curves = [c['curve_name'] for c in comparison]
                            fig_c = plot_comparison(original_data, las_data, common_curves)
                            if fig_c:
                                st.plotly_chart(fig_c, use_container_width=True)
                            non_identical = [c for c in comparison if not c['identical']]
                            if non_identical:
                                st.warning(f"⚠️ {len(non_identical)} منحنيات غير متطابقة")
                            else:
                                st.success("✅ جميع المنحنيات متطابقة!")
                    except Exception as e:
                        st.warning(f"تعذرت المقارنة: {e}")
            else:
                failed_files.append((file.name, error))
            file.seek(0)
        
        progress_bar.progress(100)
        status_text.text("✅ تم الانتهاء!")
        
        st.markdown("### 📦 نتائج التحويل")
        col1, col2 = st.columns(2)
        with col1: st.success(f"✅ نجح: {len(converted_files)} ملف")
        with col2:
            if failed_files: st.error(f"❌ فشل: {len(failed_files)} ملف")
        if failed_files:
            with st.expander("❌ الملفات الفاشلة"):
                for name, error in failed_files:
                    st.write(f"- **{name}**: {error}")
        
        if converted_files:
            if compress and len(converted_files) > 1:
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
                    for filename, data in converted_files:
                        zf.writestr(filename, data)
                st.download_button(
                    label=f"📥 تحميل ZIP ({len(converted_files)} ملف)",
                    data=zip_buffer.getvalue(),
                    file_name=f"converted_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip",
                    mime="application/zip",
                    use_container_width=True
                )
            else:
                for filename, data in converted_files:
                    st.download_button(
                        label=f"📥 تحميل {filename}",
                        data=data,
                        file_name=filename,
                        mime="application/octet-stream" if output_format == "dlis" else "text/plain",
                        use_container_width=True
                    )

else:
    st.info("👆 ارفع ملفات LIS أو DLIS لتبدأ")

st.markdown("---")
st.caption("💡 مفتوح المصدر - يدعم LIS و DLIS مع مقارنة البيانات")
