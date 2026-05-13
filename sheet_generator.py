# -*- coding: utf-8 -*-
"""
مولد أوراق الإجابة PDF
"""

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm, cm
from reportlab.lib.colors import black, white, grey, lightgrey
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import os


class SheetGenerator:
    """مولد ورقة إجابة Bubble Sheet"""
    
    def __init__(self):
        self.page_width, self.page_height = A4
        self.margin = 15 * mm
    
    def generate(self, exam, output_path):
        """توليد ملف PDF لورقة الإجابة"""
        c = canvas.Canvas(output_path, pagesize=A4)
        
        num_questions = exam['num_questions']
        num_choices = min(exam['num_choices'], 5)
        student_id_digits = exam['student_id_digits']
        
        # حدود الصفحة
        self._draw_page_border(c)
        
        # علامات المحاذاة (Fiducial markers) - في الزوايا
        self._draw_fiducial_markers(c)
        
        # العنوان
        self._draw_header(c, exam)
        
        # خانة رقم الطالب
        id_bottom = self._draw_student_id_section(c, student_id_digits)
        
        # خانة معرف الاختبار
        self._draw_exam_id_section(c, exam['id'], id_bottom)
        
        # خانات الإجابات
        self._draw_answer_section(c, num_questions, num_choices, id_bottom)
        
        # تعليمات في الأسفل
        self._draw_footer(c, exam)
        
        c.save()
        return output_path
    
    def _draw_page_border(self, c):
        """رسم إطار الصفحة"""
        c.setStrokeColor(black)
        c.setLineWidth(1)
        c.rect(self.margin - 5, self.margin - 5, 
               self.page_width - 2 * (self.margin - 5),
               self.page_height - 2 * (self.margin - 5))
    
    def _draw_fiducial_markers(self, c):
        """رسم علامات المحاذاة السوداء في الزوايا الأربعة - أساسية للكشف"""
        marker_size = 10 * mm
        positions = [
            (self.margin, self.page_height - self.margin - marker_size),  # أعلى يسار
            (self.page_width - self.margin - marker_size, self.page_height - self.margin - marker_size),  # أعلى يمين
            (self.margin, self.margin),  # أسفل يسار
            (self.page_width - self.margin - marker_size, self.margin),  # أسفل يمين
        ]
        
        c.setFillColor(black)
        for x, y in positions:
            c.rect(x, y, marker_size, marker_size, fill=1, stroke=0)
            # مربع أبيض داخلي لتمييز أفضل
            inner = 3 * mm
            c.setFillColor(white)
            c.rect(x + inner, y + inner, marker_size - 2*inner, marker_size - 2*inner, fill=1, stroke=0)
            c.setFillColor(black)
            c.rect(x + 2*inner, y + 2*inner, marker_size - 4*inner, marker_size - 4*inner, fill=1, stroke=0)
    
    def _draw_header(self, c, exam):
        """رسم العنوان"""
        y = self.page_height - self.margin - 12 * mm - 5 * mm
        
        # عنوان رئيسي
        c.setFont("Helvetica-Bold", 16)
        c.setFillColor(black)
        title = exam.get('title', 'Answer Sheet')[:40]
        c.drawCentredString(self.page_width / 2, y, title)
        
        # عنوان فرعي
        y -= 6 * mm
        c.setFont("Helvetica", 10)
        subject = exam.get('subject', '')
        if subject:
            c.drawCentredString(self.page_width / 2, y, f"Subject: {subject[:50]}")
        
        # معلومات
        y -= 5 * mm
        c.setFont("Helvetica", 9)
        info = f"Questions: {exam['num_questions']}  |  Choices: {exam['num_choices']}  |  Exam ID: {exam['id']}"
        c.drawCentredString(self.page_width / 2, y, info)
    
    def _draw_student_id_section(self, c, num_digits):
        """خانة رقم الطالب"""
        # موضع البداية
        start_x = self.margin + 5 * mm
        start_y = self.page_height - self.margin - 40 * mm
        
        bubble_radius = 2.2 * mm
        bubble_spacing_x = 6.5 * mm
        bubble_spacing_y = 5 * mm
        
        # العنوان
        c.setFont("Helvetica-Bold", 10)
        c.drawString(start_x, start_y + 5 * mm, "Student ID")
        
        # رسم خانة لكتابة الرقم
        box_y = start_y - 5 * mm
        c.setStrokeColor(black)
        c.setLineWidth(0.5)
        for i in range(num_digits):
            x = start_x + i * bubble_spacing_x
            c.rect(x - bubble_radius, box_y, bubble_radius * 2, bubble_radius * 2, fill=0, stroke=1)
        
        # رسم الدوائر للأرقام 0-9
        digit_start_y = box_y - bubble_spacing_y
        c.setFont("Helvetica", 7)
        for digit in range(10):
            y = digit_start_y - digit * bubble_spacing_y
            for col in range(num_digits):
                x = start_x + col * bubble_spacing_x
                c.circle(x, y, bubble_radius, fill=0, stroke=1)
                c.drawCentredString(x, y - 1.5, str(digit))
        
        return digit_start_y - 10 * bubble_spacing_y - 5 * mm
    
    def _draw_exam_id_section(self, c, exam_id, top_y):
        """عرض معرّف الاختبار"""
        # موضع: على يمين خانة رقم الطالب
        start_x = self.margin + 60 * mm
        start_y = self.page_height - self.margin - 40 * mm
        
        c.setFont("Helvetica-Bold", 10)
        c.drawString(start_x, start_y + 5 * mm, "Exam Code")
        
        c.setFont("Helvetica-Bold", 14)
        c.setStrokeColor(black)
        c.rect(start_x, start_y - 10 * mm, 35 * mm, 12 * mm, fill=0, stroke=1)
        c.drawCentredString(start_x + 17.5 * mm, start_y - 6 * mm, exam_id.upper())
    
    def _draw_answer_section(self, c, num_questions, num_choices, top_y):
        """رسم خانات الإجابات"""
        # تخطيط الأعمدة
        questions_per_column = 25
        if num_questions <= 25:
            num_columns = 1
            questions_per_column = num_questions
        elif num_questions <= 50:
            num_columns = 2
            questions_per_column = 25
        elif num_questions <= 100:
            num_columns = 4
            questions_per_column = 25
        elif num_questions <= 150:
            num_columns = 5
            questions_per_column = 30
        else:
            num_columns = 5
            questions_per_column = (num_questions + 4) // 5
        
        # الأبعاد
        bubble_radius = 2.0 * mm
        bubble_spacing_x = 5.5 * mm  # بين الاختيارات
        bubble_spacing_y = 5.5 * mm  # بين الأسئلة
        
        # عرض كل عمود
        column_width = (bubble_spacing_x * num_choices) + 12 * mm
        
        # حساب البداية للتوسيط
        total_width = column_width * num_columns
        available_width = self.page_width - 2 * self.margin - 10 * mm
        start_x = self.margin + 5 * mm + max(0, (available_width - total_width) / 2)
        
        start_y = top_y - 5 * mm
        
        # عنوان القسم
        c.setFont("Helvetica-Bold", 11)
        c.drawString(self.margin + 5 * mm, start_y + 3 * mm, "Answers — Fill the circle completely")
        
        # رسم الأعمدة
        choices_labels = ['A', 'B', 'C', 'D', 'E'][:num_choices]
        
        q_num = 1
        for col in range(num_columns):
            if q_num > num_questions:
                break
            
            col_x = start_x + col * column_width
            
            # رؤوس الأعمدة
            c.setFont("Helvetica-Bold", 8)
            for ci, label in enumerate(choices_labels):
                c.drawCentredString(col_x + 10 * mm + ci * bubble_spacing_x, 
                                  start_y - 2 * mm, label)
            
            # الأسئلة
            c.setFont("Helvetica", 8)
            for row in range(questions_per_column):
                if q_num > num_questions:
                    break
                
                y = start_y - 6 * mm - row * bubble_spacing_y
                
                # رقم السؤال
                c.drawRightString(col_x + 7 * mm, y - 1.5, f"{q_num}.")
                
                # دوائر الاختيارات
                c.setStrokeColor(black)
                c.setLineWidth(0.6)
                for ci in range(num_choices):
                    cx = col_x + 10 * mm + ci * bubble_spacing_x
                    c.circle(cx, y, bubble_radius, fill=0, stroke=1)
                
                q_num += 1
    
    def _draw_footer(self, c, exam):
        """تعليمات الأسفل"""
        c.setFont("Helvetica-Oblique", 8)
        c.setFillColor(grey)
        text = "Instructions: Use only a dark pen/pencil. Fill circles completely. Do not make any marks outside the circles."
        c.drawCentredString(self.page_width / 2, self.margin + 5, text)
