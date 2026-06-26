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
            
            # --- تم إصلاح المشكلة هنا ---
            # الطريقة الصحيحة في الإصدارات الحديثة من lasio لإضافة اسم البئر
            well_name_val = str(getattr(dlis_file, 'well_name', 'UNKNOWN'))
            if 'WELL' in las.well:
                las.well['WELL'].value = well_name_val
            else:
                las.well.append(lasio.HeaderItem('WELL', value=well_name_val))
            # -----------------------------
            
            for name, data in curves.items():
                if len(data) > 0:
                    las.append_curve(name, data, unit="", descr=name)
            
            if len(las.keys()) > 0:
                first_key = las.keys()[0]
                if len(las.data[first_key]) > 0:
                    depth = np.arange(len(las.data[first_key])) * 0.1524
                    # التأكد من عدم إضافة العمق إذا كان موجوداً مسبقاً باسم DEPT
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
