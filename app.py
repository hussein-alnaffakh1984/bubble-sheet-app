# -*- coding: utf-8 -*-
"""
نظام تصحيح أوراق الإجابة الآلي (Bubble Sheet Remark)
Author: Built with Claude
"""

from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for
import os
import json
import uuid
from datetime import datetime
from werkzeug.utils import secure_filename
import cv2
import numpy as np
from sheet_processor import SheetProcessor
from sheet_generator import SheetGenerator
from report_generator import ReportGenerator

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['RESULTS_FOLDER'] = 'results'
app.config['SHEETS_FOLDER'] = 'sheets'
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50 MB max
app.config['SECRET_KEY'] = 'bubble-sheet-2026'

# قاعدة بيانات بسيطة (JSON)
DB_FILE = 'database.json'

def load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {'exams': {}, 'results': []}

def save_db(data):
    with open(DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ============ الصفحات الرئيسية ============

@app.route('/')
def index():
    db = load_db()
    return render_template('index.html', 
                         total_exams=len(db['exams']),
                         total_results=len(db['results']))

@app.route('/create-exam')
def create_exam_page():
    return render_template('create_exam.html')

@app.route('/exams')
def exams_list():
    db = load_db()
    return render_template('exams.html', exams=db['exams'])

@app.route('/scan/<exam_id>')
def scan_page(exam_id):
    db = load_db()
    if exam_id not in db['exams']:
        return redirect(url_for('exams_list'))
    return render_template('scan.html', exam=db['exams'][exam_id], exam_id=exam_id)

@app.route('/results')
def results_page():
    db = load_db()
    return render_template('results.html', results=db['results'], exams=db['exams'])

@app.route('/results/<exam_id>')
def exam_results(exam_id):
    db = load_db()
    if exam_id not in db['exams']:
        return redirect(url_for('exams_list'))
    
    exam_results = [r for r in db['results'] if r['exam_id'] == exam_id]
    return render_template('exam_results.html', 
                         exam=db['exams'][exam_id], 
                         exam_id=exam_id,
                         results=exam_results)

# ============ APIs ============

@app.route('/api/create-exam', methods=['POST'])
def create_exam():
    """إنشاء اختبار جديد"""
    data = request.json
    exam_id = str(uuid.uuid4())[:8]
    
    exam = {
        'id': exam_id,
        'title': data.get('title', 'اختبار جديد'),
        'subject': data.get('subject', ''),
        'num_questions': int(data.get('num_questions', 50)),
        'num_choices': int(data.get('num_choices', 4)),
        'student_id_digits': int(data.get('student_id_digits', 8)),
        'answer_key': data.get('answer_key', []),
        'points_per_question': float(data.get('points_per_question', 1)),
        'negative_marking': bool(data.get('negative_marking', False)),
        'negative_value': float(data.get('negative_value', 0)),
        'created_at': datetime.now().isoformat(),
    }
    
    db = load_db()
    db['exams'][exam_id] = exam
    save_db(db)
    
    # توليد ورقة الإجابة PDF
    generator = SheetGenerator()
    pdf_path = os.path.join(app.config['SHEETS_FOLDER'], f'{exam_id}_template.pdf')
    generator.generate(exam, pdf_path)
    
    return jsonify({'success': True, 'exam_id': exam_id, 'pdf_url': f'/download-sheet/{exam_id}'})

@app.route('/download-sheet/<exam_id>')
def download_sheet(exam_id):
    """تحميل ورقة الإجابة PDF"""
    pdf_path = os.path.join(app.config['SHEETS_FOLDER'], f'{exam_id}_template.pdf')
    if os.path.exists(pdf_path):
        return send_file(pdf_path, as_attachment=True, download_name=f'answer_sheet_{exam_id}.pdf')
    return 'Sheet not found', 404

@app.route('/api/scan', methods=['POST'])
def scan_sheet():
    """تصحيح ورقة إجابة"""
    exam_id = request.form.get('exam_id')
    db = load_db()
    
    if exam_id not in db['exams']:
        return jsonify({'success': False, 'error': 'اختبار غير موجود'})
    
    exam = db['exams'][exam_id]
    
    if 'images' not in request.files:
        return jsonify({'success': False, 'error': 'لا توجد صور'})
    
    files = request.files.getlist('images')
    results = []
    
    processor = SheetProcessor(exam)
    
    for file in files:
        if file.filename == '':
            continue
        
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], f'{uuid.uuid4().hex[:8]}_{filename}')
        file.save(filepath)
        
        try:
            result = processor.process(filepath)
            result['exam_id'] = exam_id
            result['filename'] = filename
            result['processed_at'] = datetime.now().isoformat()
            result['result_id'] = str(uuid.uuid4())[:8]
            
            # حفظ الصورة المعالجة
            processed_path = os.path.join(app.config['RESULTS_FOLDER'], f'{result["result_id"]}_processed.jpg')
            result['processed_image'] = f'/results-image/{result["result_id"]}'
            
            db['results'].append(result)
            results.append(result)
        except Exception as e:
            results.append({
                'success': False,
                'filename': filename,
                'error': str(e)
            })
    
    save_db(db)
    
    return jsonify({'success': True, 'results': results})

@app.route('/results-image/<result_id>')
def get_result_image(result_id):
    """عرض الصورة المعالجة"""
    path = os.path.join(app.config['RESULTS_FOLDER'], f'{result_id}_processed.jpg')
    if os.path.exists(path):
        return send_file(path, mimetype='image/jpeg')
    return 'Not found', 404

@app.route('/api/export/<exam_id>')
def export_results(exam_id):
    """تصدير النتائج Excel"""
    db = load_db()
    if exam_id not in db['exams']:
        return 'Exam not found', 404
    
    exam = db['exams'][exam_id]
    results = [r for r in db['results'] if r['exam_id'] == exam_id]
    
    report = ReportGenerator()
    excel_path = os.path.join(app.config['RESULTS_FOLDER'], f'{exam_id}_results.xlsx')
    report.export_excel(exam, results, excel_path)
    
    return send_file(excel_path, as_attachment=True, 
                    download_name=f'results_{exam["title"]}_{datetime.now().strftime("%Y%m%d")}.xlsx')

@app.route('/api/delete-exam/<exam_id>', methods=['POST'])
def delete_exam(exam_id):
    db = load_db()
    if exam_id in db['exams']:
        del db['exams'][exam_id]
        db['results'] = [r for r in db['results'] if r['exam_id'] != exam_id]
        save_db(db)
    return jsonify({'success': True})

@app.route('/api/delete-result/<result_id>', methods=['POST'])
def delete_result(result_id):
    db = load_db()
    db['results'] = [r for r in db['results'] if r.get('result_id') != result_id]
    save_db(db)
    return jsonify({'success': True})

@app.route('/api/stats/<exam_id>')
def exam_stats(exam_id):
    """إحصائيات الاختبار"""
    db = load_db()
    if exam_id not in db['exams']:
        return jsonify({'error': 'not found'})
    
    exam = db['exams'][exam_id]
    results = [r for r in db['results'] if r['exam_id'] == exam_id and r.get('success')]
    
    if not results:
        return jsonify({'total': 0})
    
    scores = [r['score'] for r in results]
    percentages = [r['percentage'] for r in results]
    
    # تحليل الأسئلة
    question_analysis = []
    for q_idx in range(exam['num_questions']):
        correct_count = sum(1 for r in results if r.get('detailed_results', [])[q_idx]['is_correct'] if len(r.get('detailed_results', [])) > q_idx)
        question_analysis.append({
            'question': q_idx + 1,
            'correct': correct_count,
            'total': len(results),
            'percentage': round((correct_count / len(results) * 100) if results else 0, 1)
        })
    
    return jsonify({
        'total': len(results),
        'avg_score': round(sum(scores) / len(scores), 2),
        'avg_percentage': round(sum(percentages) / len(percentages), 2),
        'max_score': max(scores),
        'min_score': min(scores),
        'pass_count': sum(1 for p in percentages if p >= 50),
        'fail_count': sum(1 for p in percentages if p < 50),
        'question_analysis': question_analysis,
        'scores': scores,
    })

if __name__ == '__main__':
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(app.config['RESULTS_FOLDER'], exist_ok=True)
    os.makedirs(app.config['SHEETS_FOLDER'], exist_ok=True)
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
else:
    # For gunicorn deployment
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(app.config['RESULTS_FOLDER'], exist_ok=True)
    os.makedirs(app.config['SHEETS_FOLDER'], exist_ok=True)
