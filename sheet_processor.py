# -*- coding: utf-8 -*-
"""
معالج أوراق الإجابة - يستخدم OpenCV (HoughCircles + perspective correction)
"""

import cv2
import numpy as np
import os


class SheetProcessor:
    """معالج صور أوراق الإجابة"""
    
    def __init__(self, exam):
        self.exam = exam
        self.num_questions = exam['num_questions']
        self.num_choices = exam['num_choices']
        self.student_id_digits = exam['student_id_digits']
        self.answer_key = exam.get('answer_key', [])
        self.points_per_q = exam.get('points_per_question', 1)
        self.negative_marking = exam.get('negative_marking', False)
        self.negative_value = exam.get('negative_value', 0)
    
    def process(self, image_path):
        """معالجة صورة ورقة إجابة كاملة"""
        image = cv2.imread(image_path)
        if image is None:
            raise ValueError("لا يمكن قراءة الصورة")
        
        # 1) تصحيح المنظور
        warped = self._perspective_correct(image)
        if warped is None:
            warped = image
        
        # 2) كشف الدوائر
        bubbles = self._detect_bubbles_hough(warped)
        
        if len(bubbles) < 20:
            raise ValueError(f"لم يتم كشف عدد كافٍ من الدوائر ({len(bubbles)}). تأكد من جودة الصورة.")
        
        # 3) فصل المناطق
        student_id_bubbles, answer_bubbles = self._segment_bubbles(bubbles, warped.shape)
        
        # 4) قراءة رقم الطالب
        student_id = self._read_student_id(student_id_bubbles, warped)
        
        # 5) قراءة الإجابات
        answers, marked_image = self._read_answers(answer_bubbles, warped)
        
        # 6) التصحيح
        result = self._grade(answers)
        result['student_id'] = student_id
        result['success'] = True
        
        # 7) حفظ صورة النتيجة
        result_id = result.get('result_id', os.path.basename(image_path).split('.')[0])
        output_dir = 'results'
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, f'{result_id}_processed.jpg')
        cv2.imwrite(output_path, marked_image)
        result['processed_image_path'] = output_path
        
        return result
    
    def _perspective_correct(self, image):
        """تصحيح منظور الورقة - يطبق فقط إذا كان هناك تشوه ملحوظ"""
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edged = cv2.Canny(blurred, 75, 200)
        
        kernel = np.ones((3, 3), np.uint8)
        edged = cv2.dilate(edged, kernel, iterations=1)
        
        contours, _ = cv2.findContours(edged, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        contours = sorted(contours, key=cv2.contourArea, reverse=True)
        
        paper_contour = None
        for c in contours[:10]:
            peri = cv2.arcLength(c, True)
            approx = cv2.approxPolyDP(c, 0.02 * peri, True)
            if len(approx) == 4:
                area = cv2.contourArea(c)
                if area > image.shape[0] * image.shape[1] * 0.5:
                    paper_contour = approx
                    break
        
        if paper_contour is None:
            return None
        
        pts = paper_contour.reshape(4, 2)
        rect = self._order_points(pts)
        (tl, tr, br, bl) = rect
        
        # تحقق من مستوى التشوه: إذا كان الانحراف بسيطاً، لا نطبق التحويل
        # حساب الاختلاف بين أبعاد الجانبين
        widthA = np.linalg.norm(br - bl)
        widthB = np.linalg.norm(tr - tl)
        heightA = np.linalg.norm(tr - br)
        heightB = np.linalg.norm(tl - bl)
        
        width_diff = abs(widthA - widthB) / max(widthA, widthB)
        height_diff = abs(heightA - heightB) / max(heightA, heightB)
        
        # إذا كان التشوه أقل من 2% في كلا الاتجاهين، لا داعي للتصحيح
        if width_diff < 0.02 and height_diff < 0.02:
            return None
        
        maxWidth = max(int(widthA), int(widthB))
        maxHeight = max(int(heightA), int(heightB))
        
        if maxWidth > maxHeight:
            maxHeight = int(maxWidth * 1.414)
        else:
            maxWidth = int(maxHeight / 1.414)
        
        dst = np.array([
            [0, 0],
            [maxWidth - 1, 0],
            [maxWidth - 1, maxHeight - 1],
            [0, maxHeight - 1]], dtype="float32")
        
        M = cv2.getPerspectiveTransform(rect, dst)
        return cv2.warpPerspective(image, M, (maxWidth, maxHeight))
    
    def _order_points(self, pts):
        rect = np.zeros((4, 2), dtype="float32")
        s = pts.sum(axis=1)
        rect[0] = pts[np.argmin(s)]
        rect[2] = pts[np.argmax(s)]
        diff = np.diff(pts, axis=1)
        rect[1] = pts[np.argmin(diff)]
        rect[3] = pts[np.argmax(diff)]
        return rect
    
    def _detect_bubbles_hough(self, image):
        """كشف الدوائر باستخدام HoughCircles - مسوحات متعددة"""
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 1)
        
        page_width = image.shape[1]
        page_height = image.shape[0]
        min_r = max(6, int(page_width * 0.006))
        max_r = max(20, int(page_width * 0.018))
        min_dist = max(15, int(page_width * 0.015))
        
        all_raw = []
        
        # المسح 1: على كامل الصورة
        c1 = cv2.HoughCircles(
            blurred, cv2.HOUGH_GRADIENT,
            dp=1, minDist=min_dist,
            param1=50, param2=20,
            minRadius=min_r, maxRadius=max_r
        )
        if c1 is not None:
            for x, y, r in c1[0].astype(int):
                all_raw.append((int(x), int(y), int(r)))
        
        # المسح 2: حساسية أعلى للالتقاط الإضافي
        c2 = cv2.HoughCircles(
            blurred, cv2.HOUGH_GRADIENT,
            dp=1, minDist=min_dist,
            param1=50, param2=14,
            minRadius=min_r, maxRadius=max_r
        )
        if c2 is not None:
            for x, y, r in c2[0].astype(int):
                all_raw.append((int(x), int(y), int(r)))
        
        # المسح 3: على الثلث السفلي بحساسية عالية جداً (لالتقاط الصفوف الأخيرة)
        bottom_start = int(page_height * 0.65)
        bottom_region = blurred[bottom_start:, :]
        c3 = cv2.HoughCircles(
            bottom_region, cv2.HOUGH_GRADIENT,
            dp=1, minDist=min_dist,
            param1=50, param2=10,
            minRadius=min_r, maxRadius=max_r
        )
        if c3 is not None:
            for x, y, r in c3[0].astype(int):
                # إضافة الـ offset
                all_raw.append((int(x), int(y) + bottom_start, int(r)))
        
        # المسح 4: على آخر 20% فقط (الصفوف الأخيرة من الإجابات)
        last_start = int(page_height * 0.78)
        last_region = blurred[last_start:int(page_height * 0.95), :]
        c4 = cv2.HoughCircles(
            last_region, cv2.HOUGH_GRADIENT,
            dp=1, minDist=min_dist,
            param1=40, param2=9,
            minRadius=min_r, maxRadius=max_r
        )
        if c4 is not None:
            for x, y, r in c4[0].astype(int):
                all_raw.append((int(x), int(y) + last_start, int(r)))
        
        if not all_raw:
            return []
        
        # دمج الدوائر المتداخلة (نفس الدائرة من المسوحات)
        merged = []
        for x, y, r in all_raw:
            duplicate_idx = -1
            for i, (mx, my, mr) in enumerate(merged):
                if abs(x - mx) < min_dist * 0.6 and abs(y - my) < min_dist * 0.6:
                    duplicate_idx = i
                    break
            if duplicate_idx >= 0:
                mx, my, mr = merged[duplicate_idx]
                merged[duplicate_idx] = ((x + mx) // 2, (y + my) // 2, max(r, mr))
            else:
                merged.append((x, y, r))
        
        # فلتر إحصائي للقطر
        radii = sorted([r for _, _, r in merged])
        if radii:
            median_r = radii[len(radii) // 2]
            merged = [(x, y, r) for x, y, r in merged if abs(r - median_r) <= 6]
        
        bubbles = [{'x': x, 'y': y, 'r': r} for x, y, r in merged]
        return bubbles
    
    def _segment_bubbles(self, bubbles, image_shape):
        """فصل الدوائر إلى مناطق"""
        h, w = image_shape[:2]
        
        # رقم الطالب: أعلى يسار، تجنب Exam Code
        id_y_max = h * 0.42
        id_x_max = w * 0.32
        
        student_id_bubbles = [b for b in bubbles 
                              if b['y'] < id_y_max and b['x'] < id_x_max]
        
        # الإجابات: تحت المنطقة العلوية وقبل الـ footer
        answer_bubbles = [b for b in bubbles 
                          if b['y'] >= id_y_max * 1.1 
                          and b['y'] < h * 0.92]
        
        return student_id_bubbles, answer_bubbles
    
    def _is_filled(self, image, bubble):
        """نسبة التظليل في الدائرة (0-1)"""
        x, y, r = bubble['x'], bubble['y'], bubble['r']
        inner_r = max(3, int(r * 0.7))
        
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
        
        h, w = gray.shape
        y1, y2 = max(0, y - inner_r), min(h, y + inner_r + 1)
        x1, x2 = max(0, x - inner_r), min(w, x + inner_r + 1)
        
        roi = gray[y1:y2, x1:x2]
        if roi.size == 0:
            return 0
        
        mask = np.zeros(roi.shape, dtype=np.uint8)
        cv2.circle(mask, (roi.shape[1] // 2, roi.shape[0] // 2), inner_r - 1, 255, -1)
        
        mean_val = cv2.mean(roi, mask=mask)[0]
        return 1.0 - (mean_val / 255.0)
    
    def _cluster_1d(self, values, tolerance=15):
        """تجميع قيم متقاربة"""
        if not values:
            return []
        sorted_vals = sorted(values)
        clusters = [[sorted_vals[0]]]
        for v in sorted_vals[1:]:
            if v - clusters[-1][-1] <= tolerance:
                clusters[-1].append(v)
            else:
                clusters.append([v])
        return [int(sum(c) / len(c)) for c in clusters]
    
    def _group_by_rows(self, bubbles, tolerance=15):
        """تجميع الدوائر حسب الصفوف"""
        if not bubbles:
            return []
        sorted_bubbles = sorted(bubbles, key=lambda b: b['y'])
        rows = [[sorted_bubbles[0]]]
        for b in sorted_bubbles[1:]:
            if abs(b['y'] - rows[-1][-1]['y']) <= tolerance:
                rows[-1].append(b)
            else:
                rows.append([b])
        for row in rows:
            row.sort(key=lambda b: b['x'])
        return rows
    
    def _read_student_id(self, bubbles, image):
        """قراءة رقم الطالب - يقبل فقط الأعمدة بحوالي 10 دوائر (0-9)"""
        if not bubbles:
            return "0" * self.student_id_digits
        
        # تجميع أوّلي بـ tolerance صغير لتفادي دمج الأعمدة المتقاربة
        xs = sorted([b['x'] for b in bubbles])
        
        # نستخدم histogram لإيجاد الأعمدة الأكثر كثافة
        # كل عمود حقيقي لرقم الطالب يحتوي ~10 دوائر بنفس x تقريباً
        # لكن بعد perspective correction، قد تتفاوت قيم x ضمن العمود
        from collections import Counter
        # quantize x values - أكبر للتسامح مع perspective
        x_quantized = [round(x / 8) * 8 for x in xs]
        x_counts = Counter(x_quantized)
        
        # احتفظ فقط بقيم x التي تظهر 6 مرات أو أكثر
        dense_xs = sorted([x for x, count in x_counts.items() if count >= 6])
        
        if not dense_xs:
            # احتياط: استخدم التجميع التقليدي
            col_centers = self._cluster_1d([b['x'] for b in bubbles], tolerance=20)
        else:
            # تجميع القيم الكثيفة المتجاورة
            col_centers = self._cluster_1d(dense_xs, tolerance=15)
        
        if not col_centers:
            return "0" * self.student_id_digits
        
        # احصل على دوائر كل عمود (نطاق أعرض للتسامح مع perspective)
        valid_columns = []
        for col_x in col_centers:
            col_bubbles = [b for b in bubbles if abs(b['x'] - col_x) < 18]
            if 7 <= len(col_bubbles) <= 13:
                valid_columns.append((col_x, col_bubbles))
        
        # ترتيب حسب x (من اليسار لليمين)
        valid_columns.sort(key=lambda c: c[0])
        
        # خذ فقط أول student_id_digits من الأعمدة
        valid_columns = valid_columns[:self.student_id_digits]
        
        # حساب y_start: صف الأرقام 0 - مشترك بين الأعمدة
        # نأخذ أصغر y من المجموعات المنتظمة ونتحقق من تكراره
        all_uniform_groups = []
        for col_x, col_bubbles in valid_columns:
            col_bubbles.sort(key=lambda b: b['y'])
            grp = self._find_uniform_group(col_bubbles, target_count=10)
            if grp:
                all_uniform_groups.append((col_x, col_bubbles, grp))
        
        if not all_uniform_groups:
            return "0" * self.student_id_digits
        
        # ابحث عن الـ y الأكثر شيوعاً كبداية لصف الرقم 0
        first_ys = [grp[0]['y'] for _, _, grp in all_uniform_groups]
        # تجميع الـ y المتقاربة
        first_ys_sorted = sorted(first_ys)
        clusters = [[first_ys_sorted[0]]]
        for y in first_ys_sorted[1:]:
            if y - clusters[-1][-1] < 15:
                clusters[-1].append(y)
            else:
                clusters.append([y])
        # أكبر مجموعة هي الـ y الحقيقي للرقم 0
        biggest_cluster = max(clusters, key=len)
        y_start = sum(biggest_cluster) / len(biggest_cluster)
        
        digits = []
        for col_x, col_bubbles, grp in all_uniform_groups:
            # إذا كان أول دائرة في المجموعة بعيدة عن y_start، نتجاهل بداية المجموعة
            if abs(grp[0]['y'] - y_start) > 15:
                # ابحث عن الدائرة الأقرب لـ y_start
                grp_adjusted = [b for b in col_bubbles if b['y'] >= y_start - 15]
                grp_adjusted = self._find_uniform_group(grp_adjusted, target_count=10)
                if grp_adjusted:
                    grp = grp_adjusted
            
            best_digit = -1
            best_fill = 0
            threshold = 0.4
            
            for digit, b in enumerate(grp):
                fill = self._is_filled(image, b)
                if fill > best_fill and fill > threshold:
                    best_fill = fill
                    best_digit = digit
            
            digits.append(str(best_digit) if best_digit >= 0 else '0')
        
        student_id = ''.join(digits)
        while len(student_id) < self.student_id_digits:
            student_id = '0' + student_id
        return student_id[:self.student_id_digits]
    
    def _find_uniform_group(self, bubbles, target_count=10):
        """ابحث عن أفضل مجموعة من target_count دوائر بمسافات y منتظمة"""
        if len(bubbles) < target_count:
            return bubbles
        
        # رتب حسب y
        sorted_bs = sorted(bubbles, key=lambda b: b['y'])
        ys = [b['y'] for b in sorted_bs]
        
        # المسافة المتوقعة بين الأرقام (طبيعية ~ 38-44 بكسل)
        # نحسب الفروق الزوجية
        diffs = []
        for i in range(len(ys) - 1):
            diffs.append(ys[i+1] - ys[i])
        if not diffs:
            return sorted_bs[:target_count]
        
        # الفرق المتوسط (median)
        sorted_diffs = sorted(diffs)
        median_diff = sorted_diffs[len(sorted_diffs) // 2]
        
        # ابحث عن أطول تسلسل من الدوائر بمسافات قريبة من الـ median
        best_seq = []
        current_seq = [sorted_bs[0]]
        for i in range(1, len(sorted_bs)):
            diff = sorted_bs[i]['y'] - current_seq[-1]['y']
            # اعتبر الفرق "منتظم" إذا كان ضمن ±30% من الـ median
            if abs(diff - median_diff) <= median_diff * 0.3:
                current_seq.append(sorted_bs[i])
            else:
                if len(current_seq) > len(best_seq):
                    best_seq = current_seq
                current_seq = [sorted_bs[i]]
        if len(current_seq) > len(best_seq):
            best_seq = current_seq
        
        # أعد أول target_count من أفضل تسلسل
        return best_seq[:target_count]
    
    def _read_answers(self, bubbles, image):
        """قراءة الإجابات - منطق محسّن باستخدام أعمدة x المشتركة"""
        marked = image.copy()
        
        if not bubbles:
            return [None] * self.num_questions, marked
        
        # إزالة الدوائر المتداخلة (نفس الموقع) أولاً
        dedup_bubbles = []
        for b in bubbles:
            is_dup = False
            for db in dedup_bubbles:
                if abs(b['x'] - db['x']) < 12 and abs(b['y'] - db['y']) < 12:
                    is_dup = True
                    break
            if not is_dup:
                dedup_bubbles.append(b)
        bubbles = dedup_bubbles
        
        # تجميع الصفوف
        rows = self._group_by_rows(bubbles, tolerance=15)
        
        if not rows:
            return [None] * self.num_questions, marked
        
        # فلترة الصفوف الحقيقية: تحتوي على num_choices دوائر على الأقل في الأعمدة المشتركة
        # نحسب أولاً أعمدة الإجابات الحقيقية
        from collections import Counter
        all_xs = [b['x'] for b in bubbles]
        x_quantized_temp = [round(x / 8) * 8 for x in all_xs]
        temp_x_counts = Counter(x_quantized_temp)
        min_app_temp = max(5, len(rows) // 2)
        temp_dense_xs = sorted([x for x, count in temp_x_counts.items() if count >= min_app_temp])
        temp_cols = self._cluster_1d(temp_dense_xs, tolerance=15)
        
        # احسب نطاق x للإجابات
        if temp_cols and len(temp_cols) >= self.num_choices:
            valid_x_min = temp_cols[0] - 15
            valid_x_max = temp_cols[-1] + 15
            # احتفظ فقط بالصفوف التي تحوي num_choices دوائر في نطاق الإجابات
            real_rows = []
            for row in rows:
                in_range = [b for b in row if valid_x_min <= b['x'] <= valid_x_max]
                if len(in_range) >= self.num_choices:
                    real_rows.append(row)
            rows = real_rows
        
        # إعادة دمج الصفوف المتقاربة جداً (نفس السؤال مكتشف مرتين في y مختلفة قليلاً)
        rows.sort(key=lambda r: r[0]['y'])
        merged_rows = []
        for row in rows:
            if merged_rows and abs(row[0]['y'] - merged_rows[-1][0]['y']) < 20:
                # ادمج مع آخر صف
                merged_rows[-1].extend(row)
            else:
                merged_rows.append(list(row))
        rows = merged_rows
        
        # تحديد أعمدة الإجابات المشتركة: نجمع جميع x ونبحث عن القيم الأكثر شيوعاً
        # كل عمود إجابة حقيقي يظهر في كثير من الصفوف
        from collections import Counter
        all_xs = [b['x'] for b in bubbles]
        x_quantized = [round(x / 8) * 8 for x in all_xs]
        x_counts = Counter(x_quantized)
        
        # أعمدة الإجابات المشتركة: تظهر في 50%+ من الصفوف المتوقعة
        min_appearances = max(5, len(rows) // 2)
        dense_xs = sorted([x for x, count in x_counts.items() if count >= min_appearances])
        
        # تجميع dense_xs لإيجاد مركز كل عمود إجابة
        column_centers = self._cluster_1d(dense_xs, tolerance=15)
        
        # نأخذ أكثر `num_q_columns * num_choices` كمية من الأعمدة المركزية
        # كل عمود من الأسئلة يحتوي num_choices أعمدة من الدوائر
        # عمود واحد للأسئلة في تصميمنا الحالي
        
        if len(column_centers) < self.num_choices:
            # نسخة احتياطية - استخدم المنطق القديم
            return self._read_answers_fallback(bubbles, image, marked)
        
        # تحديد أعمدة الأسئلة (مجموعات من num_choices أعمدة متقاربة)
        # احسب الفجوات
        gaps = [column_centers[i+1] - column_centers[i] for i in range(len(column_centers) - 1)]
        if gaps:
            median_gap = sorted(gaps)[len(gaps) // 2]
            # فجوة كبيرة (> 1.8 * median) = حدود بين أعمدة الأسئلة
            question_columns = []  # كل عنصر: قائمة من num_choices من x-centers
            current = [column_centers[0]]
            for i in range(1, len(column_centers)):
                if gaps[i-1] > median_gap * 1.8:
                    if len(current) >= self.num_choices:
                        question_columns.append(current[:self.num_choices])
                    current = [column_centers[i]]
                else:
                    current.append(column_centers[i])
            if len(current) >= self.num_choices:
                question_columns.append(current[:self.num_choices])
        else:
            question_columns = [column_centers[:self.num_choices]]
        
        if not question_columns:
            return self._read_answers_fallback(bubbles, image, marked)
        
        # لكل عمود من الأسئلة، استخرج الصفوف
        all_questions = []
        
        for q_col_centers in question_columns:
            x_min = q_col_centers[0] - 15
            x_max = q_col_centers[-1] + 15
            
            # الصفوف التي تحتوي على دوائر في هذا النطاق
            for row in rows:
                # احصل على الدوائر الأقرب للأعمدة المشتركة فقط
                row_in_range = [b for b in row if x_min <= b['x'] <= x_max]
                
                if len(row_in_range) < self.num_choices:
                    continue
                
                # إذا كان عدد الدوائر زائداً، اختر الأقرب لكل عمود مشترك
                if len(row_in_range) > self.num_choices:
                    chosen = []
                    used = set()
                    for cx in q_col_centers:
                        # ابحث عن الدائرة الأقرب لـ cx من الدوائر غير المستخدمة
                        best = None
                        best_dist = float('inf')
                        for j, b in enumerate(row_in_range):
                            if j in used:
                                continue
                            dist = abs(b['x'] - cx)
                            if dist < best_dist:
                                best_dist = dist
                                best = (j, b)
                        if best:
                            used.add(best[0])
                            chosen.append(best[1])
                    
                    if len(chosen) == self.num_choices:
                        chosen.sort(key=lambda b: b['x'])
                        all_questions.append((row[0]['y'], chosen))
                else:
                    # تماماً num_choices دوائر
                    row_in_range.sort(key=lambda b: b['x'])
                    all_questions.append((row[0]['y'], row_in_range))
        
        # ترتيب حسب العمود ثم y
        if len(question_columns) > 1:
            def col_idx(item):
                bx = item[1][0]['x']
                for i, qc in enumerate(question_columns):
                    if qc[0] - 15 <= bx <= qc[-1] + 15:
                        return i
                return 99
            all_questions.sort(key=lambda x: (col_idx(x), x[0]))
        else:
            all_questions.sort(key=lambda x: x[0])
        
        # إزالة الأسئلة المكررة (نفس y تقريباً) - تحدث بسبب المسوحات المتعددة
        deduplicated = []
        for y, row in all_questions:
            is_duplicate = False
            for prev_y, prev_row in deduplicated:
                # نفس الـ y و قريب جداً في x
                if abs(y - prev_y) < 20 and abs(row[0]['x'] - prev_row[0]['x']) < 30:
                    is_duplicate = True
                    break
            if not is_duplicate:
                deduplicated.append((y, row))
        all_questions = deduplicated
        
        # تحديد الإجابة لكل سؤال
        answers = []
        threshold = 0.4
        
        for q_idx, (y, row) in enumerate(all_questions):
            if q_idx >= self.num_questions:
                break
            
            fills = [self._is_filled(image, b) for b in row]
            max_fill = max(fills) if fills else 0
            
            if max_fill < threshold:
                answers.append(None)
                continue
            
            sorted_fills = sorted(fills, reverse=True)
            if len(sorted_fills) > 1 and sorted_fills[1] > 0.85 * sorted_fills[0] and sorted_fills[1] > threshold:
                answers.append(None)
                continue
            
            selected_idx = fills.index(max_fill)
            choice = ['A', 'B', 'C', 'D', 'E'][selected_idx]
            answers.append(choice)
            
            b = row[selected_idx]
            if q_idx < len(self.answer_key):
                correct_ans = self.answer_key[q_idx]
                color = (0, 200, 0) if choice == correct_ans else (0, 0, 220)
            else:
                color = (255, 100, 0)
            
            cv2.circle(marked, (b['x'], b['y']), b['r'] + 3, color, 3)
        
        while len(answers) < self.num_questions:
            answers.append(None)
        
        return answers[:self.num_questions], marked
    
    def _read_answers_fallback(self, bubbles, image, marked):
        """منطق احتياطي بسيط لقراءة الإجابات"""
        if not bubbles:
            return [None] * self.num_questions, marked
        
        rows = self._group_by_rows(bubbles, tolerance=15)
        valid_rows = [r for r in rows if len(r) >= self.num_choices]
        valid_rows.sort(key=lambda r: r[0]['y'])
        
        answers = []
        threshold = 0.4
        
        for q_idx, row in enumerate(valid_rows):
            if q_idx >= self.num_questions:
                break
            
            row_use = row[:self.num_choices]
            fills = [self._is_filled(image, b) for b in row_use]
            max_fill = max(fills) if fills else 0
            
            if max_fill < threshold:
                answers.append(None)
                continue
            
            sorted_fills = sorted(fills, reverse=True)
            if len(sorted_fills) > 1 and sorted_fills[1] > 0.85 * sorted_fills[0] and sorted_fills[1] > threshold:
                answers.append(None)
                continue
            
            selected_idx = fills.index(max_fill)
            choice = ['A', 'B', 'C', 'D', 'E'][selected_idx]
            answers.append(choice)
            
            b = row_use[selected_idx]
            if q_idx < len(self.answer_key):
                correct_ans = self.answer_key[q_idx]
                color = (0, 200, 0) if choice == correct_ans else (0, 0, 220)
            else:
                color = (255, 100, 0)
            cv2.circle(marked, (b['x'], b['y']), b['r'] + 3, color, 3)
        
        while len(answers) < self.num_questions:
            answers.append(None)
        return answers[:self.num_questions], marked
    
    def _grade(self, answers):
        """تصحيح الإجابات"""
        if not self.answer_key:
            return {
                'answers': answers,
                'score': 0,
                'percentage': 0,
                'correct': 0,
                'wrong': 0,
                'blank': sum(1 for a in answers if a is None),
                'total': self.num_questions,
                'detailed_results': [
                    {'question': i + 1, 'student_answer': a, 'correct_answer': None, 
                     'is_correct': False, 'is_blank': a is None}
                    for i, a in enumerate(answers)
                ]
            }
        
        correct = 0
        wrong = 0
        blank = 0
        score = 0
        detailed = []
        
        for i in range(self.num_questions):
            student_ans = answers[i] if i < len(answers) else None
            correct_ans = self.answer_key[i] if i < len(self.answer_key) else None
            
            is_blank = student_ans is None
            is_correct = (student_ans == correct_ans) and not is_blank
            
            if is_blank:
                blank += 1
            elif is_correct:
                correct += 1
                score += self.points_per_q
            else:
                wrong += 1
                if self.negative_marking:
                    score -= self.negative_value
            
            detailed.append({
                'question': i + 1,
                'student_answer': student_ans,
                'correct_answer': correct_ans,
                'is_correct': is_correct,
                'is_blank': is_blank
            })
        
        total_possible = self.num_questions * self.points_per_q
        percentage = (score / total_possible * 100) if total_possible > 0 else 0
        
        return {
            'answers': answers,
            'score': round(max(0, score), 2),
            'percentage': round(max(0, percentage), 2),
            'correct': correct,
            'wrong': wrong,
            'blank': blank,
            'total': self.num_questions,
            'total_possible': total_possible,
            'detailed_results': detailed
        }
