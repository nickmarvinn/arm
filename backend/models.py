from datetime import datetime
from database import db

class Employee(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    phone = db.Column(db.String(20))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Track cumulative fees generated (NEW)
    cumulative_fees = db.Column(db.Float, default=0.0)
    # Track cumulative commission earned
    cumulative_commission = db.Column(db.Float, default=0.0)
    
    # Commission structure stored as JSON
    commission_structure = db.Column(db.JSON, nullable=False)
    
    # Relationships
    placements = db.relationship('Placement', backref='employee', lazy=True, cascade="all, delete-orphan")
    earnings = db.relationship('Earning', backref='employee', lazy=True, cascade="all, delete-orphan")
    
    def __repr__(self):
        return f'<Employee {self.name}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'email': self.email,
            'phone': self.phone,
            'cumulative_fees': self.cumulative_fees,
            'cumulative_commission': self.cumulative_commission,
            'commission_structure': self.commission_structure,
            'created_at': self.created_at.isoformat()
        }
    
    def calculate_current_rate_based_on_fees(self):
        """Calculate current commission rate based on cumulative fees"""
        structure = self.commission_structure
        cumulative_fees = self.cumulative_fees
        
        # Start with base rate
        current_rate = structure.get('base_rate', 0.0)
        
        # Check tiers - apply when cumulative fees REACHES threshold
        for tier in sorted(structure.get('tiers', []), key=lambda x: x['threshold']):
            if cumulative_fees >= tier['threshold']:
                current_rate = tier['rate']
        
        # Apply cap if exists
        if structure.get('cap') is not None:
            current_rate = min(current_rate, structure['cap'])
        
        return current_rate
    
    def calculate_commission_based_on_fees(self, fee_amount):
        """
        Calculate commission where tiers are based on CUMULATIVE FEES
        Tiers apply when cumulative fees REACH OR EXCEED the threshold
        """
        structure = self.commission_structure
        cumulative_fees_before = self.cumulative_fees
        remaining_fee = fee_amount
        total_commission = 0
        breakdown = []
        
        # Get commission structure
        base_rate = structure.get('base_rate', 0.0)
        tiers = sorted(structure.get('tiers', []), key=lambda x: x['threshold'])
        cap = structure.get('cap')
        
        # Start with current position in fees
        current_fee_position = cumulative_fees_before
        
        # Determine starting rate (tier applies when reaching fee threshold)
        current_rate = base_rate
        for tier in tiers:
            if current_fee_position >= tier['threshold']:
                current_rate = tier['rate']
        
        # Apply cap if exists
        if cap is not None:
            current_rate = min(current_rate, cap)
        
        # Process the fee amount
        while remaining_fee > 0:
            # Find next fee threshold (if any)
            next_threshold = None
            next_rate = current_rate
            
            # Look for the next tier threshold GREATER than current fee position
            for tier in tiers:
                if tier['threshold'] > current_fee_position:
                    next_threshold = tier['threshold']
                    next_rate = tier['rate']
                    break
            
            # Effective rate (respecting cap)
            effective_rate = min(current_rate, cap) if cap is not None else current_rate
            
            if next_threshold is not None:
                # Calculate fee space until next threshold
                fee_space = next_threshold - current_fee_position
                
                if fee_space <= remaining_fee:
                    # This segment will reach the next threshold
                    segment_fee = fee_space
                    segment_commission = segment_fee * effective_rate
                    
                    breakdown.append({
                        'segment': len(breakdown) + 1,
                        'from_cumulative_fees': current_fee_position,
                        'to_cumulative_fees': next_threshold,
                        'fee_amount': segment_fee,
                        'rate': effective_rate,
                        'commission': segment_commission,
                        'description': f"${segment_fee:,.2f} at {effective_rate*100:.1f}% (reaches ${next_threshold:,.0f} threshold)"
                    })
                    
                    total_commission += segment_commission
                    current_fee_position = next_threshold
                    remaining_fee -= segment_fee
                    
                    # Move to next tier rate
                    current_rate = next_rate
                    
                    # Re-apply cap for new rate
                    if cap is not None:
                        current_rate = min(current_rate, cap)
                else:
                    # Remaining fee stays in current tier
                    segment_fee = remaining_fee
                    segment_commission = segment_fee * effective_rate
                    
                    breakdown.append({
                        'segment': len(breakdown) + 1,
                        'from_cumulative_fees': current_fee_position,
                        'to_cumulative_fees': current_fee_position + segment_fee,
                        'fee_amount': segment_fee,
                        'rate': effective_rate,
                        'commission': segment_commission,
                        'description': f"${segment_fee:,.2f} at {effective_rate*100:.1f}%"
                    })
                    
                    total_commission += segment_commission
                    current_fee_position += segment_fee
                    remaining_fee = 0
            else:
                # No more thresholds - we're at the highest tier
                segment_fee = remaining_fee
                segment_commission = segment_fee * effective_rate
                
                breakdown.append({
                    'segment': len(breakdown) + 1,
                    'from_cumulative_fees': current_fee_position,
                    'to_cumulative_fees': current_fee_position + segment_fee,
                    'fee_amount': segment_fee,
                    'rate': effective_rate,
                    'commission': segment_commission,
                    'description': f"${segment_fee:,.2f} at {effective_rate*100:.1f}%"
                })
                
                total_commission += segment_commission
                current_fee_position += segment_fee
                remaining_fee = 0
        
        # Calculate new rate based on final fee position
        new_rate = base_rate
        for tier in tiers:
            if current_fee_position >= tier['threshold']:
                new_rate = tier['rate']
        
        if cap is not None:
            new_rate = min(new_rate, cap)
        
        return {
            'total_commission': total_commission,
            'breakdown': breakdown,
            'cumulative_fees_before': cumulative_fees_before,
            'cumulative_fees_after': current_fee_position,
            'cumulative_commission_before': self.cumulative_commission,
            'cumulative_commission_after': self.cumulative_commission + total_commission,
            'new_rate': new_rate
        }


class YearlySummary(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    year = db.Column(db.Integer, nullable=False)
    total_placements = db.Column(db.Integer, default=0)
    total_fees = db.Column(db.Float, default=0.0)
    total_commissions = db.Column(db.Float, default=0.0)
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<YearlySummary {self.year}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'year': self.year,
            'total_placements': self.total_placements,
            'total_fees': self.total_fees,
            'total_commissions': self.total_commissions,
            'recorded_at': self.recorded_at.isoformat()
        }








class Placement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    candidate_name = db.Column(db.String(100), nullable=False)
    bank_name = db.Column(db.String(100), nullable=False)
    starting_salary = db.Column(db.Float, nullable=False)
    fee_percentage = db.Column(db.Float, nullable=False)
    placement_date = db.Column(db.DateTime, default=datetime.utcnow)

    placement_year = db.Column(db.Integer, default=lambda: datetime.utcnow().year)
    
    # Store commission details
    commission_amount = db.Column(db.Float, default=0.0)
    commission_rate_used = db.Column(db.Float, default=0.0)
    commission_breakdown = db.Column(db.JSON)
    
    # Relationships
    employee_id = db.Column(db.Integer, db.ForeignKey('employee.id', ondelete='CASCADE'), nullable=False)
    
    def __repr__(self):
        return f'<Placement {self.candidate_name} at {self.bank_name}>'
    
    def to_dict(self):
        fee_amount = self.starting_salary * self.fee_percentage
        return {
            'id': self.id,
            'candidate_name': self.candidate_name,
            'bank_name': self.bank_name,
            'starting_salary': self.starting_salary,
            'fee_percentage': self.fee_percentage,
            'fee_amount': fee_amount,
            'commission_amount': self.commission_amount,
            'commission_rate_used': self.commission_rate_used,
            'commission_breakdown': self.commission_breakdown,
            'placement_date': self.placement_date.isoformat(),
            'employee_id': self.employee_id
        }
    
    def get_fee_amount(self):
        return self.starting_salary * self.fee_percentage

class Earning(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    amount = db.Column(db.Float, nullable=False)
    placement_id = db.Column(db.Integer, db.ForeignKey('placement.id'))
    employee_id = db.Column(db.Integer, db.ForeignKey('employee.id'), nullable=False)
    calculated_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    placement = db.relationship('Placement', backref='earnings_entries')
    
    def __repr__(self):
        return f'<Earning ${self.amount} for Employee {self.employee_id}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'amount': self.amount,
            'placement_id': self.placement_id,
            'employee_id': self.employee_id,
            'calculated_at': self.calculated_at.isoformat()
        }