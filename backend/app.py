from flask import Flask, send_from_directory, request, jsonify
from flask_cors import CORS
from database import db
from models import Employee, Placement, Earning
from datetime import datetime
import os

app = Flask(__name__, static_folder='./build', static_url_path='')
CORS(app)

# Configuration
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///commission_tracker.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key')

db.init_app(app)

# Create tables
with app.app_context():
    db.create_all()

def parse_date(date_string):
    """Parse various date string formats"""
    if not date_string:
        return datetime.utcnow()
    
    # Clean the string - remove timezone Z if present
    if date_string.endswith('Z'):
        date_string = date_string[:-1]
    
    # Try multiple formats
    formats = [
        '%Y-%m-%dT%H:%M:%S.%f',  # With milliseconds
        '%Y-%m-%dT%H:%M:%S',     # Without milliseconds
        '%Y-%m-%d %H:%M:%S',     # Space instead of T
        '%Y-%m-%d'               # Just date
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(date_string, fmt)
        except ValueError:
            continue
    
    # If all else fails, return current time
    print(f"Could not parse date: {date_string}, using current time")
    return datetime.utcnow()

# Routes

@app.route('/',
defaults={'path': ''})
@app.route('/<path:path>')
def serve_react(path):
    build_path = os.path.join(app.static_folder, path)
    if path != "" and os.path.exists(build_path):
        return send_from_directory(app.static_folder, path)
    else:
        return send_from_directory(app.static_folder, 'index.html')



@app.route('/')
def index():
    return jsonify({"message": "Commission Tracker API"})

# Employee Routes
@app.route('/api/employees', methods=['GET'])
def get_employees():
    employees = Employee.query.all()
    return jsonify([employee.to_dict() for employee in employees])

@app.route('/api/employees/<int:id>', methods=['GET'])
def get_employee(id):
    employee = Employee.query.get_or_404(id)
    return jsonify(employee.to_dict())

@app.route('/api/employees', methods=['POST'])
def create_employee():
    data = request.json
    
    if 'commission_structure' not in data:
        return jsonify({"error": "Commission structure is required"}), 400
    
    employee = Employee(
        name=data['name'],
        email=data['email'],
        phone=data.get('phone', ''),
        commission_structure=data['commission_structure']
    )
    
    db.session.add(employee)
    db.session.commit()
    
    return jsonify(employee.to_dict()), 201

@app.route('/api/employees/<int:id>', methods=['PUT'])
def update_employee(id):
    employee = Employee.query.get_or_404(id)
    data = request.json
    
    employee.name = data.get('name', employee.name)
    employee.email = data.get('email', employee.email)
    employee.phone = data.get('phone', employee.phone)
    
    if 'commission_structure' in data:
        employee.commission_structure = data['commission_structure']
    
    db.session.commit()
    return jsonify(employee.to_dict())

@app.route('/api/employees/<int:id>', methods=['DELETE'])
def delete_employee(id):
    employee = Employee.query.get_or_404(id)

    db.session.delete(employee)
    db.session.commit()
    return jsonify({"message": "Employee deleted"})

# Placement Routes
@app.route('/api/placements', methods=['GET'])
def get_placements():
    placements = Placement.query.all()
    result = []
    for placement in placements:
        placement_dict = placement.to_dict()
        placement_dict['employee_name'] = placement.employee.name if placement.employee else None
        result.append(placement_dict)
    
    return jsonify(result)


@app.route('/api/placements/<int:id>', methods=['DELETE'])
def delete_placement(id):
    placement = Placement.query.get_or_404(id)

    db.session.delete(placement)
    db.session.commit()
    return jsonify({"message": "Placement deleted"})



@app.route('/api/placements', methods=['POST'])
def create_placement():
    data = request.json
    
    # Parse date
    placement_date = parse_date(data.get('placement_date'))
    
    # Calculate fee amount
    fee_amount = float(data['starting_salary']) * (float(data['fee_percentage']) / 100)
    
    # Get employee
    employee = Employee.query.get(data['employee_id'])
    if not employee:
        return jsonify({"error": "Employee not found"}), 404
    
    # Calculate commission based on cumulative FEES (NEW)
    commission_result = employee.calculate_commission_based_on_fees(fee_amount)
    
    # Create placement
    placement = Placement(
        candidate_name=data['candidate_name'],
        bank_name=data['bank_name'],
        starting_salary=float(data['starting_salary']),
        fee_percentage=float(data['fee_percentage']) / 100,
        employee_id=data['employee_id'],
        placement_date=placement_date,
        commission_amount=commission_result['total_commission'],
        commission_rate_used=commission_result['new_rate'],
        commission_breakdown=commission_result['breakdown']
    )
    
    db.session.add(placement)
    
    # Create earning record
    earning = Earning(
        amount=commission_result['total_commission'],
        placement_id=placement.id,
        employee_id=data['employee_id']
    )
    
    db.session.add(earning)
    
    # Update employee's cumulative fees AND commission (NEW)
    employee.cumulative_fees += fee_amount
    employee.cumulative_commission += commission_result['total_commission']
    
    db.session.commit()
    
    return jsonify({
        'placement': placement.to_dict(),
        'commission_result': commission_result,
        'employee': {
            'id': employee.id,
            'name': employee.name,
            'cumulative_fees_before': commission_result['cumulative_fees_before'],
            'cumulative_fees_after': employee.cumulative_fees,
            'cumulative_commission_before': commission_result['cumulative_commission_before'],
            'cumulative_commission_after': employee.cumulative_commission,
            'new_rate': commission_result['new_rate'] * 100
        }
    }), 201


@app.route('/api/employees/reset-ytd', methods=['POST'])
def reset_ytd_totals():
    """Reset all employees' YTD cumulative fees and commission to zero"""
    try:
        # Get all employees
        employees = Employee.query.all()
        
        reset_count = 0
        for employee in employees:
            employee.cumulative_fees = 0.0
            employee.cumulative_commission = 0.0
        db.session.commit()
        
        return jsonify({
            'message': f'Successfully reset YTD totals for {reset_count} employees',
            'reset_count': reset_count,
            'timestamp': datetime.utcnow().isoformat()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to reset YTD totals: {str(e)}'}), 500



# Commission calculation preview
@app.route('/api/employees/<int:id>/calculate-commission', methods=['POST'])
def calculate_commission_preview(id):
    """Preview commission calculation without saving"""
    employee = Employee.query.get_or_404(id)
    data = request.json
    
    fee_amount = float(data.get('fee_amount', 0))
    commission_result = employee.calculate_commission_based_on_fees(fee_amount)
    
    return jsonify({
        'employee': {
            'id': employee.id,
            'name': employee.name,
            'cumulative_fees': employee.cumulative_fees,
            'cumulative_commission': employee.cumulative_commission,
            'current_rate': employee.calculate_current_rate_based_on_fees() * 100
        },
        'commission_result': commission_result
    })

# Dashboard/Report Routes
@app.route('/api/dashboard/summary', methods=['GET'])
def get_dashboard_summary():
    total_placements = Placement.query.count()
    total_employees = Employee.query.count()
    
    total_fees = db.session.query(db.func.sum(Placement.starting_salary * Placement.fee_percentage)).scalar() or 0
    total_commissions = db.session.query(db.func.sum(Earning.amount)).scalar() or 0
    
    # Get recent placements with employee names
    recent_placements = Placement.query.order_by(Placement.placement_date.desc()).limit(5).all()
    
    # Format placements with employee names
    placements_with_employees = []
    for placement in recent_placements:
        placement_dict = placement.to_dict()
        if placement.employee:
            placement_dict['employee_name'] = placement.employee.name
        else:
            placement_dict['employee_name'] = 'Unknown'
        placements_with_employees.append(placement_dict)
    
    return jsonify({
        'total_placements': total_placements,
        'total_employees': total_employees,
        'total_fees': total_fees,
        'total_commissions': total_commissions,
        'recent_placements': placements_with_employees
    })

@app.route('/api/employees/<int:id>/earnings', methods=['GET'])
def get_employee_earnings(id):
    employee = Employee.query.get_or_404(id)
    
    earnings = Earning.query.filter_by(employee_id=id).all()
    placements = Placement.query.filter_by(employee_id=id).all()
    
    cumulative_earnings = []
    running_total = 0
    
    for earning in sorted(earnings, key=lambda x: x.calculated_at):
        running_total += earning.amount
        cumulative_earnings.append({
            'date': earning.calculated_at.isoformat(),
            'amount': earning.amount,
            'cumulative': running_total,
            'placement_id': earning.placement_id
        })
    
    return jsonify({
        'employee': employee.to_dict(),
        'earnings': [e.to_dict() for e in earnings],
        'cumulative_earnings': cumulative_earnings,
        'total_earned': running_total,
        'current_commission_rate': employee.calculate_current_rate() * 100,
        'placements': [p.to_dict() for p in placements]
    })

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)