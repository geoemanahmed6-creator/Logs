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
import struct  # لقراءة البيانات الثنائية

st.set_page_config(page_title="Log Converter Pro - Batch", layout="wide")

# Custom CSS للتحسين
st.markdown("""
<style>
    .report-box {
        padding: 15px;
        border-radius: 10px;
        margin: 10px 0;
    }
    .quality-good {
        background-color: #d4edda;
        border: 1px solid #c3e6cb;
        color: #155724;
    }
    .quality-warning {
        background-color: #fff3cd;
        border: 1px solid #ffc107;
        color: #856404;
    }
    .quality-error {
        background-color: #f8d7da;
        border: 1px solid #f5c6cb;
        color: #721c24;
    }
    .match-perfect {
        background-color: #d4edda;
        border: 2px solid #28a745;
        padding: 10px;
        border-radius: 10px;
    }
    .match-warning {
        background-color: #fff3cd;
        border: 2px solid #ffc107;
        padding: 10px;
        border-radius: 10px;
    }
    .match-error {
        background-color: #f8d7da;
        border: 2px solid #dc3545;
        padding: 10px;
        border-radius: 10px;
    }
    .stProgress > div > div {
        background-color: #4CAF50;
    }
</style>
""", unsafe_allow_html=True)

st.title("🛢️ Log Converter Pro - مع المقارنة")
st.markdown("قم بتحويل ملفات LIS و DLIS إلى LAS أو DLIS مع مقارنة البيانات قبل وبعد التحويل")

# ==============================================
# دوال قراءة الملفات بطرق متعددة (زي Techlog)
# ==============================================

def read_file_with_fallback(file_bytes, file_name):
    """محاولة قراءة الملف بأكثر من طريقة (زي Techlog)"""
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
        try:
            Path(tmp_path).unlink()
        except:
            pass
    
    # الطريقة 2: LIS (صريح)
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
        try:
            Path(tmp_path).unlink()
        except:
            pass
    
    # الطريقة 3: محاولة قراءة كـ LAS (لو كان ملف نصي)
    try:
        las = lasio.read(io.BytesIO(file_bytes))
        if las.curves:
            # تحويل LAS لكائن يشبه DLIS
            class LasWrapper:
                def __init__(self, las):
                    self.las = las
                    self.well_name = las.well.WELL.value if hasattr(las.well, 'WELL') else "LAS_FILE"
                
                @property
                def frames(self):
                    class FrameWrapper:
                        def __init__(self, las):
                            self.las = las
                        def curves(self):
                            class CurveWrapper:
                                def __init__(self, mnemonic, data):
                                    self.name = mnemonic
                                    self._data = data
                                def curves(self):
                                    return self._data
                            return [CurveWrapper(c.mnemonic, c.data) for c in self.las.curves]
                    return [FrameWrapper(self.las)]
            return [LasWrapper(las)], "LAS", None
    except Exception as e:
        errors.append(f"LAS: {str(e)}")
    
    # الطريقة 4: محاولة قراءة البيانات الخام (Raw Binary) - زي DPLOG
    try:
        # محاولة استخراج float32 من الملف الثنائي
        data = np.frombuffer(file_bytes, dtype=np.float32)
        if len(data) > 10:  # على الأقل 10 قراءات
            class RawWrapper:
                def __init__(self, data):
                    self.data = data
                    self.well_name = "RAW_BINARY"
                @property
                def frames(self):
                    class FrameWrapper:
                        def __init__(self, data):
                            self.data = data
                        def curves(self):
                            class CurveWrapper:
                                def __init__(self, data):
                                    self.name = "RAW_DATA"
                                    self._data = data
                                def curves(self):
                                    return self._data
                            return [CurveWrapper(self.data)]
                    return [FrameWrapper(self.data)]
            return [RawWrapper(data)], "RAW_BINARY", None
    except Exception as e:
        errors.append(f"RAW_BINARY: {str(e)}")
    
    return None, None, f"فشل بكل الطرق: {'; '.join(errors)}"


# ==============================================
# دوال قراءة وعرض البيانات (معدلة)
# ==============================================

def read_log_file(file_bytes, file_name):
    """قراءة ملف الوج باستخدام طريقة الفشل الذهبي"""
    try:
        dlis_files, method, error = read_file_with_fallback(file_bytes, file_name)
        
        if error or not dlis_files:
            return None, error or "لا يمكن قراءة الملف"
        
        dlis_file = dlis_files[0]
        
        # استخراج جميع البيانات
        all_data = {}
        curves_info = []
        frames_info = []
        
        # قراءة الأطر (Frames)
        for i, frame in enumerate(dlis_file.frames):
            frame_name = getattr(frame, 'name', f"Frame_{i}")
            curves_in_frame = []
            
            for curve in frame.curves():
                try:
                    data = curve.curves()
                    if data is not None and len(data) > 0:
                        curve_name = getattr(curve, 'name', f"Curve_{len(curves_in_frame)}")
                        curves_in_frame.append({
                            'name': curve_name,
                            'data': data,
                            'units': getattr(curve, 'units', ''),
                            'count': len(data)
                        })
                        all_data[curve_name] = data
                except Exception as e:
                    continue
            
            if curves_in_frame:
                frames_info.append({
                    'name': frame_name,
                    'curves': curves_in_frame,
                    'count': len(curves_in_frame)
                })
        
        # معلومات البئر
        well_info = {
            'well_name': getattr(dlis_file, 'well_name', 'غير معروف'),
            'field_name': getattr(dlis_file, 'field_name', 'غير معروف'),
            'total_curves': len(all_data),
            'total_frames': len(frames_info),
            'method': method  # الطريقة اللي اشتغلت
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


# ==============================================
# دوال التحويل (معدلة)
# ==============================================

def convert_file_fast(file_bytes, file_name, output_format="las", progress_callback=None):
    """تحويل سريع مع دعم التقدم وطرق متعددة"""
    try:
        dlis_files, method, error = read_file_with_fallback(file_bytes, file_name)
        
        if error or not dlis_files:
            return None, error or "لا يمكن قراءة الملف", None
        
        dlis_file = dlis_files[0]
        
        if progress_callback:
            progress_callback(50)
        
        if output_format == "las":
            # استخراج البيانات بسرعة
            curves_data = {}
            frame = None
            
            for frm in dlis_file.frames:
                if len(frm.curves()) > 0:
                    frame = frm
                    break
            
            if frame is None:
                return None, "لا توجد منحنيات", None
            
            for curve in frame.curves():
                try:
                    data = curve.curves()
                    if data is not None and len(data) > 0:
                        curve_name = getattr(curve, 'name', f"Curve_{len(curves_data)}")
                        curves_data[curve_name] = data
                except:
                    continue
            
            if not curves_data:
                return None, "لا توجد بيانات قابلة للقراءة", None
            
            # إنشاء LAS بسرعة
            las = lasio.LASFile()
            las.well = lasio.WellItem("WELL", value=getattr(dlis_file, 'well_name', 'UNKNOWN'))
            
            for curve_name, data in curves_data.items():
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
            
            return output.getvalue().encode('utf-8'), None, curves_data
        
        elif output_format == "dlis":
            if progress_callback:
                progress_callback(100)
            return file_bytes, None, None
    
    except Exception as e:
        return None, str(e), None


# ==============================================
# دوال المقارنة والجودة (نفسها مع تعديلات بسيطة)
# ==============================================

def read_las_file(file_bytes):
    """قراءة ملف LAS"""
    try:
        las_text = file_bytes.decode('utf-8')
        las = lasio.read(io.StringIO(las_text))
        
        data_dict = {}
        for curve in las.curves:
            if curve.data is not None and len(curve.data) > 0:
                data_dict[curve.mnemonic] = curve.data
        
        return data_dict, None
    except Exception as e:
        return None, str(e)


def compare_data(original_data, converted_data, curve_names=None):
    """مقارنة البيانات الأصلية والمحولة"""
    comparison_results = []
    
    if curve_names is None:
        curve_names = set(original_data.keys()) & set(converted_data.keys())
    
    for curve_name in curve_names:
        orig = np.array(original_data[curve_name])
        conv = np.array(converted_data[curve_name])
        
        min_len = min(len(orig), len(conv))
        orig = orig[:min_len]
        conv = conv[:min_len]
        
        diff = orig - conv
        abs_diff = np.abs(diff)
        
        valid_mask = ~(np.isnan(orig) | np.isnan(conv))
        if np.sum(valid_mask) > 0:
            orig_valid = orig[valid_mask]
            conv_valid = conv[valid_mask]
            diff_valid = diff[valid_mask]
            
            result = {
                'curve_name': curve_name,
                'points_compared': np.sum(valid_mask),
                'max_abs_diff': np.max(np.abs(diff_valid)) if len(diff_valid) > 0 else 0,
                'mean_abs_diff': np.mean(np.abs(diff_valid)) if len(diff_valid) > 0 else 0,
                'std_diff': np.std(diff_valid) if len(diff_valid) > 0 else 0,
                'max_percent_diff': np.max(np.abs(diff_valid / (orig_valid + 1e-10))) * 100 if len(diff_valid) > 0 else 0,
                'mean_percent_diff': np.mean(np.abs(diff_valid / (orig_valid + 1e-10))) * 100 if len(diff_valid) > 0 else 0,
                'identical': np.allclose(orig_valid, conv_valid, rtol=1e-10, atol=1e-10),
                'orig_min': np.min(orig_valid),
                'orig_max': np.max(orig_valid),
                'conv_min': np.min(conv_valid),
                'conv_max': np.max(conv_valid),
                'nan_count_orig': np.isnan(orig).sum(),
                'nan_count_conv': np.isnan(conv).sum()
            }
            comparison_results.append(result)
    
    return comparison_results


def analyze_file_quality(file_bytes, file_name):
    """تحليل جودة ملف الوج مع دعم الطرق المتعددة"""
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
        
        # عدد المنحنيات
        curves_count = 0
        for frame in dlis_file.frames:
            curves_count += len(frame.curves())
        report["curves_count"] = curves_count
        
        if curves_count == 0:
            report["warnings"].append("لا توجد منحنيات في الملف")
            report["quality_score"] -= 30
        
        # معلومات البئر
        report["info"]["well_name"] = getattr(dlis_file, 'well_name', 'غير معروف')
        report["info"]["field_name"] = getattr(dlis_file, 'field_name', 'غير معروف')
        report["info"]["method"] = method
        
        # نطاق العمق
        for frame in dlis_file.frames:
            for curve in frame.curves():
                try:
                    data = curve.curves()
                    if data is not None and len(data) > 0:
                        report["depth_range"] = {
                            "min": float(np.min(data)) if len(data) > 0 else 0,
                            "max": float(np.max(data)) if len(data) > 0 else 0,
                            "points": len(data)
                        }
                        break
                except:
                    continue
                if report["depth_range"]:
                    break
        
        # التحقق من البيانات المفقودة
        missing_data = 0
        total_points = 0
        for frame in dlis_file.frames:
            for curve in frame.curves():
                try:
                    data = curve.curves()
                    if data is not None:
                        total_points += len(data)
                        missing_data += np.isnan(data).sum()
                except:
                    continue
        
        if total_points > 0:
            missing_percent = (missing_data / total_points) * 100
            if missing_percent > 10:
                report["warnings"].append(f"{missing_percent:.1f}% من البيانات مفقودة")
                report["quality_score"] -= missing_percent / 2
            report["info"]["missing_data_percent"] = f"{missing_percent:.1f}%"
        
        # حجم الملف
        if report["file_size_kb"] > 10000:
            report["warnings"].append("حجم الملف كبير جداً قد يؤثر على الأداء")
            report["quality_score"] -= 5
        
    except Exception as e:
        report["status"] = "❌ فشل"
        report["errors"].append(str(e))
        report["quality_score"] = 0
    finally:
        try:
            pass
        except:
            pass
    
    report["quality_score"] = max(0, min(100, report["quality_score"]))
    if report["quality_score"] >= 80:
        report["quality_grade"] = "⭐ ممتاز"
    elif report["quality_score"] >= 50:
        report["quality_grade"] = "⚠️ جيد"
    else:
        report["quality_grade"] = "❌ ضعيف"
    
    return report


# ==============================================
# دوال الرسوم البيانية
# ==============================================

def plot_log_data(data_dict, max_curves=6):
    """عرض الرسوم البيانية للبيانات"""
    if not data_dict:
        return None
    
    curves_to_plot = []
    for name, data in data_dict.items():
        if len(data) > 10 and not np.isnan(data).all():
            curves_to_plot.append((name, data))
    
    curves_to_plot.sort(key=lambda x: len(x[1]), reverse=True)
    curves_to_plot = curves_to_plot[:max_curves]
    
    if not curves_to_plot:
        return None
    
    n_curves = len(curves_to_plot)
    fig = make_subplots(
        rows=1, 
        cols=n_curves,
        subplot_titles=[name for name, _ in curves_to_plot],
        shared_yaxes=True,
        horizontal_spacing=0.05
    )
    
    for i, (name, data) in enumerate(curves_to_plot):
        col = i + 1
        depth = np.arange(len(data)) * 0.1524
        
        fig.add_trace(
            go.Scatter(
                x=data,
                y=depth,
                mode='lines',
                name=name,
                line=dict(width=1.5),
                hovertemplate=f'<b>{name}</b><br>القيمة: %{{x:.2f}}<br>العمق: %{{y:.2f}} م<extra></extra>'
            ),
            row=1, col=col
        )
        
        fig.update_xaxes(
            title_text="القيمة",
            row=1, col=col,
            zeroline=False,
            gridcolor='lightgray'
        )
        fig.update_yaxes(
            title_text="العمق (م)" if i == 0 else "",
            row=1, col=col,
            autorange='reversed',
            gridcolor='lightgray'
        )
    
    fig.update_layout(
        height=500,
        showlegend=False,
        template='plotly_white',
        margin=dict(l=50, r=20, t=80, b=50),
        hovermode='y unified'
    )
    
    return fig


def plot_comparison(original_data, converted_data, curve_names, max_curves=4):
    """عرض مقارنة بيانية بين البيانات الأصلية والمحولة"""
    if not curve_names:
        return None
    
    common_curves = [c for c in curve_names if c in original_data and c in converted_data]
    common_curves = common_curves[:max_curves]
    
    if not common_curves:
        return None
    
    n_curves = len(common_curves)
    
    fig = make_subplots(
        rows=1, 
        cols=n_curves * 2,
        subplot_titles=[f"{name} (أصلي)" for name in common_curves] + [f"{name} (محول)" for name in common_curves],
        shared_yaxes=True,
        horizontal_spacing=0.03
    )
    
    for i, curve_name in enumerate(common_curves):
        orig = np.array(original_data[curve_name])
        conv = np.array(converted_data[curve_name])
        
        min_len = min(len(orig), len(conv))
        orig = orig[:min_len]
        conv = conv[:min_len]
        depth = np.arange(min_len) * 0.1524
        
        col = i * 2 + 1
        fig.add_trace(
            go.Scatter(
                x=orig,
                y=depth,
                mode='lines',
                name=f'{curve_name} (أصلي)',
                line=dict(color='blue', width=2),
                hovertemplate=f'<b>{curve_name} (أصلي)</b><br>القيمة: %{{x:.2f}}<br>العمق: %{{y:.2f}} م<extra></extra>'
            ),
            row=1, col=col
        )
        
        col = i * 2 + 2
        fig.add_trace(
            go.Scatter(
                x=conv,
                y=depth,
                mode='lines',
                name=f'{curve_name} (محول)',
                line=dict(color='red', width=2, dash='dash'),
                hovertemplate=f'<b>{curve_name} (محول)</b><br>القيمة: %{{x:.2f}}<br>العمق: %{{y:.2f}} م<extra></extra>'
            ),
            row=1, col=col
        )
        
        fig.update_xaxes(title_text="القيمة", row=1, col=col, zeroline=False, gridcolor='lightgray')
        fig.update_yaxes(
            title_text="العمق (م)" if i == 0 else "",
            row=1, col=col,
            autorange='reversed',
            gridcolor='lightgray'
        )
    
    fig.update_layout(
        height=600,
        showlegend=False,
        template='plotly_white',
        margin=dict(l=50, r=20, t=80, b=50),
        hovermode='y unified'
    )
    
    return fig


def plot_diff_comparison(original_data, converted_data, curve_names, max_curves=4):
    """عرض الرسم البياني للاختلافات"""
    common_curves = [c for c in curve_names if c in original_data and c in converted_data]
    common_curves = common_curves[:max_curves]
    
    if not common_curves:
        return None
    
    n_curves = len(common_curves)
    fig = make_subplots(
        rows=1, 
        cols=n_curves,
        subplot_titles=[f"{name} - الفرق" for name in common_curves],
        shared_yaxes=True,
        horizontal_spacing=0.05
    )
    
    for i, curve_name in enumerate(common_curves):
        orig = np.array(original_data[curve_name])
        conv = np.array(converted_data[curve_name])
        
        min_len = min(len(orig), len(conv))
        orig = orig[:min_len]
        conv = conv[:min_len]
        diff = orig - conv
        depth = np.arange(min_len) * 0.1524
        
        col = i + 1
        fig.add_trace(
            go.Scatter(
                x=diff,
                y=depth,
                mode='lines',
                name=f'{curve_name}',
                line=dict(color='purple', width=1.5),
                hovertemplate=f'<b>{curve_name}</b><br>الفرق: %{{x:.6f}}<br>العمق: %{{y:.2f}} م<extra></extra>'
            ),
            row=1, col=col
        )
        
        fig.add_hline(y=0, line_dash="dash", line_color="gray", row=1, col=col)
        
        fig.update_xaxes(title_text="الفرق", row=1, col=col, zeroline=False, gridcolor='lightgray')
        fig.update_yaxes(
            title_text="العمق (م)" if i == 0 else "",
            row=1, col=col,
            autorange='reversed',
            gridcolor='lightgray'
        )
    
    fig.update_layout(
        height=500,
        showlegend=False,
        template='plotly_white',
        margin=dict(l=50, r=20, t=80, b=50),
        hovermode='y unified'
    )
    
    return fig


def display_data_stats(data_dict):
    """عرض إحصائيات البيانات"""
    stats_data = []
    for name, data in data_dict.items():
        if len(data) > 0:
            clean_data = data[~np.isnan(data)]
            if len(clean_data) > 0:
                stats_data.append({
                    'المنحنى': name,
                    'عدد النقاط': len(data),
                    'القيمة الصغرى': f"{np.min(clean_data):.2f}",
                    'القيمة القصوى': f"{np.max(clean_data):.2f}",
                    'المتوسط': f"{np.mean(clean_data):.2f}",
                    'الانحراف المعياري': f"{np.std(clean_data):.2f}",
                    'البيانات المفقودة': f"{(len(data) - len(clean_data)) / len(data) * 100:.1f}%"
                })
    
    if stats_data:
        df = pd.DataFrame(stats_data)
        return df
    return None


def display_comparison_stats(comparison_results):
    """عرض إحصائيات المقارنة"""
    if not comparison_results:
        st.info("لا توجد بيانات للمقارنة")
        return
    
    df = pd.DataFrame(comparison_results)
    
    identical_count = sum(df['identical'])
    total_curves = len(df)
    
    col1, col2, col3 = st.columns(3)
    with col1:
        if identical_count == total_curves:
            st.markdown("""
            <div class="match-perfect">
                ✅ <b>مطابقة تامة!</b><br>
                جميع المنحنيات متطابقة بنسبة 100%
            </div>
            """, unsafe_allow_html=True)
        elif identical_count / total_curves > 0.8:
            st.markdown("""
            <div class="match-warning">
                ⚠️ <b>مطابقة جيدة جداً</b><br>
                معظم المنحنيات متطابقة
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown("""
            <div class="match-error">
                ❌ <b>اختلافات ملحوظة!</b><br>
                راجع البيانات بعناية
            </div>
            """, unsafe_allow_html=True)
    
    with col2:
        st.metric("📊 عدد المنحنيات المقارنة", total_curves)
    with col3:
        st.metric("✅ منحنيات متطابقة", f"{identical_count}/{total_curves}")
    
    st.markdown("#### 📋 تفاصيل المقارنة لكل منحنى")
    
    display_df = df[['curve_name', 'points_compared', 'max_abs_diff', 'mean_abs_diff', 
                     'max_percent_diff', 'mean_percent_diff', 'identical', 
                     'nan_count_orig', 'nan_count_conv']].copy()
    
    def highlight_identical(row):
        if row['identical']:
            return ['background-color: #d4edda'] * len(row)
        else:
            return ['background-color: #f8d7da'] * len(row)
    
    st.dataframe(
        display_df.style.apply(highlight_identical, axis=1),
        use_container_width=True,
        column_config={
            'curve_name': 'اسم المنحنى',
            'points_compared': 'النقاط المقارنة',
            'max_abs_diff': 'أقصى فرق مطلق',
            'mean_abs_diff': 'متوسط الفرق المطلق',
            'max_percent_diff': 'أقصى فرق نسبي %',
            'mean_percent_diff': 'متوسط الفرق النسبي %',
            'identical': 'مطابق؟',
            'nan_count_orig': 'NaN (أصلي)',
            'nan_count_conv': 'NaN (محول)'
        }
    )


# ==============================================
# واجهة المستخدم الرئيسية
# ==============================================

uploaded_files = st.file_uploader(
    "📂 اختر ملفات LIS أو DLIS (يمكنك اختيار عدة ملفات)",
    type=['lis', 'dlis', 'LIS', 'DLIS', 'las', 'LAS'],
    accept_multiple_files=True,
    help="اختر ملف واحد أو أكثر للتحويل - يدعم LIS و DLIS و LAS"
)

if uploaded_files:
    st.markdown(f"### ✅ تم رفع {len(uploaded_files)} ملف")
    
    # عرض معاينة لكل ملف
    for file in uploaded_files:
        with st.expander(f"📄 عرض بيانات: {file.name}"):
            file.seek(0)
            
            with st.spinner("جاري قراءة الملف..."):
                data, error = read_log_file(file.read(), file.name)
                file.seek(0)
                
                if data and error is None:
                    # عرض طريقة القراءة المستخدمة
                    st.info(f"📌 تمت القراءة باستخدام: **{data.get('method', 'غير معروف')}**")
                    
                    # معلومات البئر
                    col1, col2, col3, col4 = st.columns(4)
                    with col1:
                        st.metric("🏷️ اسم البئر", data['well_info']['well_name'])
                    with col2:
                        st.metric("📊 عدد المنحنيات", data['well_info']['total_curves'])
                    with col3:
                        st.metric("📁 عدد الأطر", data['well_info']['total_frames'])
                    with col4:
                        st.metric("🔧 الطريقة", data['well_info']['method'])
                    
                    # عرض الرسوم البيانية
                    st.markdown("#### 📈 الرسوم البيانية للمنحنيات الرئيسية")
                    fig = plot_log_data(data['all_data'])
                    if fig:
                        st.plotly_chart(fig, use_container_width=True)
                    else:
                        st.warning("لا توجد بيانات كافية لعرض رسوم بيانية")
                    
                    # عرض إحصائيات البيانات
                    st.markdown("#### 📊 إحصائيات البيانات")
                    stats_df = display_data_stats(data['all_data'])
                    if stats_df is not None and not stats_df.empty:
                        st.dataframe(stats_df, use_container_width=True)
                    else:
                        st.info("لا توجد بيانات إحصائية متاحة")
                    
                    # عرض المنحنيات
                    with st.expander("📋 عرض جميع المنحنيات"):
                        for frame in data['frames']:
                            st.markdown(f"**Frame: {frame['name']}** ({frame['count']} منحنيات)")
                            for curve in frame['curves']:
                                st.write(f"- {curve['name']} (عدد النقاط: {curve['count']})")
                else:
                    st.error(f"❌ خطأ في قراءة الملف: {error}")
                    st.warning("💡 نصيحة: تأكد أن الملف بصيغة LIS أو DLIS صالحة. بعض ملفات LIS القديمة تحتاج برامج متخصصة مثل Techlog.")
    
    # خيارات التحويل
    st.markdown("---")
    col1, col2, col3 = st.columns(3)
    with col1:
        output_format = st.selectbox(
            "🔄 صيغة الإخراج:",
            options=["las", "dlis"],
            format_func=lambda x: "LAS (نصي)" if x == "las" else "DLIS (ثنائي)"
        )
    
    with col2:
        compress = st.checkbox("📦 ضغط الملفات في ZIP واحد", value=True)
    
    with col3:
        enable_comparison = st.checkbox("🔍 تمكين المقارنة", value=True)
    
    # زر التحويل
    if st.button("🚀 تحويل الكل", type="primary", use_container_width=True):
        # تحليل الجودة أولاً
        with st.spinner("🔍 جاري تحليل جودة الملفات..."):
            quality_reports = []
            progress_bar = st.progress(0)
            
            for i, file in enumerate(uploaded_files):
                progress_bar.progress((i + 1) / len(uploaded_files))
                report = analyze_file_quality(file.read(), file.name)
                quality_reports.append(report)
                file.seek(0)
            
            st.success("✅ تم تحليل الجودة")
        
        # عرض تقرير الجودة
        st.markdown("### 📊 تقرير جودة الملفات")
        
        total_files = len(quality_reports)
        success_files = sum(1 for r in quality_reports if r["status"] == "✅ نجاح")
        avg_score = np.mean([r["quality_score"] for r in quality_reports])
        
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("📁 إجمالي الملفات", total_files)
        with col2:
            st.metric("✅ صالحة للتحويل", success_files)
        with col3:
            st.metric("📊 متوسط الجودة", f"{avg_score:.0f}%")
        with col4:
            grade = "⭐ ممتاز" if avg_score >= 80 else "⚠️ جيد" if avg_score >= 50 else "❌ ضعيف"
            st.metric("🏆 التقييم العام", grade)
        
        for report in quality_reports:
            with st.expander(f"{report['status']} {report['file_name']} - الجودة: {report['quality_score']:.0f}% ({report['quality_grade']})"):
                col1, col2 = st.columns(2)
                with col1:
                    st.write(f"**📏 الحجم:** {report['file_size_kb']:.1f} KB")
                    st.write(f"**📊 عدد المنحنيات:** {report['curves_count']}")
                    st.write(f"**🔧 طريقة القراءة:** {report['method_used']}")
                    if report["depth_range"]:
                        st.write(f"**📍 نقاط العمق:** {report['depth_range']['points']}")
                with col2:
                    st.write(f"**🏷️ اسم البئر:** {report['info'].get('well_name', 'غير معروف')}")
                    if 'missing_data_percent' in report['info']:
                        st.write(f"**🔍 البيانات المفقودة:** {report['info']['missing_data_percent']}")
                
                if report["warnings"]:
                    st.warning(f"⚠️ تحذيرات: {', '.join(report['warnings'])}")
                if report["errors"]:
                    st.error(f"❌ أخطاء: {', '.join(report['errors'])}")
        
        # بدء عملية التحويل
        st.markdown("### ⚡ جاري التحويل والمقارنة...")
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
            result, error, converted_data = convert_file_fast(
                file.read(), 
                file.name, 
                output_format,
                update_progress
            )
            
            if result:
                new_filename = Path(file.name).stem + f"_converted.{output_format}"
                converted_files.append((new_filename, result))
                
                if enable_comparison and original_data and output_format == "las" and converted_data:
                    las_data, _ = read_las_file(result)
                    
                    if las_data:
                        comparison = compare_data(original_data, las_data)
                        all_comparisons.append({
                            'file_name': file.name,
                            'comparison': comparison
                        })
                        
                        st.markdown(f"---")
                        st.markdown(f"### 🔍 مقارنة البيانات: {file.name}")
                        
                        if comparison:
                            display_comparison_stats(comparison)
                            
                            common_curves = [c['curve_name'] for c in comparison]
                            
                            st.markdown("#### 📈 مقارنة بيانية (أصلي vs محول)")
                            fig_compare = plot_comparison(original_data, las_data, common_curves)
                            if fig_compare:
                                st.plotly_chart(fig_compare, use_container_width=True)
                            
                            st.markdown("#### 📊 اختلافات البيانات")
                            fig_diff = plot_diff_comparison(original_data, las_data, common_curves)
                            if fig_diff:
                                st.plotly_chart(fig_diff, use_container_width=True)
                            
                            non_identical = [c for c in comparison if not c['identical']]
                            if non_identical:
                                st.warning(f"⚠️ {len(non_identical)} منحنيات غير متطابقة تماماً")
                                with st.expander("عرض التفاصيل"):
                                    for item in non_identical:
                                        st.write(f"- **{item['curve_name']}**: أقصى فرق {item['max_abs_diff']:.6f}, متوسط الفرق {item['mean_abs_diff']:.6f}")
                            else:
                                st.success("✅ جميع المنحنيات متطابقة تماماً!")
                        else:
                            st.info("لا توجد منحنيات مشتركة للمقارنة")
            else:
                failed_files.append((file.name, error))
            
            file.seek(0)
        
        progress_bar.progress(100)
        status_text.text("✅ تم الانتهاء من التحويل والمقارنة!")
        
        st.markdown("### 📦 نتائج التحويل")
        
        col1, col2 = st.columns(2)
        with col1:
            st.success(f"✅ نجح: {len(converted_files)} ملف")
        with col2:
            if failed_files:
                st.error(f"❌ فشل: {len(failed_files)} ملف")
        
        if failed_files:
            with st.expander("❌ الملفات التي فشل تحويلها"):
                for name, error in failed_files:
                    st.write(f"- **{name}**: {error}")
        
        if converted_files:
            if compress and len(converted_files) > 1:
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                    for filename, data in converted_files:
                        zip_file.writestr(filename, data)
                
                st.download_button(
                    label=f"📥 تحميل الكل كـ ZIP ({len(converted_files)} ملف)",
                    data=zip_buffer.getvalue(),
                    file_name=f"converted_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip",
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
        
        if st.button("📄 تصدير تقرير الجودة والمقارنة (JSON)"):
            export_data = {
                'quality_reports': quality_reports,
                'comparisons': all_comparisons,
                'timestamp': datetime.now().isoformat()
            }
            report_json = json.dumps(export_data, indent=2, default=str)
            st.download_button(
                label="📥 تحميل التقرير",
                data=report_json,
                file_name=f"full_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                mime="application/json"
            )

else:
    st.info("👆 ارفع ملفات LIS أو DLIS لتبدأ")

st.markdown("---")
st.caption("💡 تطبيق مفتوح المصدر - يدعم التحويل الدفعي مع مقارنة البيانات قبل وبعد التحويل")
