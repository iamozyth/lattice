"""
Authentication routes for NetDoc IPAM
"""
from flask import Blueprint, request, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from app import db
from app.models import User
from functools import wraps
import os

auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')


def admin_required(f):
    """Decorator to require admin role"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            return {'error': 'Admin access required'}, 403
        return f(*args, **kwargs)
    return decorated_function


@auth_bp.route('/register', methods=['POST'])
def register():
    """Register a new user (admin only or first user)"""
    try:
        data = request.get_json()
        
        # Validate input
        if not data or not data.get('username') or not data.get('password') or not data.get('email'):
            return {'error': 'Missing required fields'}, 400
        
        username = data.get('username', '').strip()
        email = data.get('email', '').strip()
        password = data.get('password', '')
        
        # Validate username
        if len(username) < 3:
            return {'error': 'Username must be at least 3 characters'}, 400
        
        if not email or '@' not in email:
            return {'error': 'Invalid email address'}, 400
        
        # Check if user already exists
        if User.query.filter_by(username=username).first():
            return {'error': 'Username already exists'}, 400
        
        if User.query.filter_by(email=email).first():
            return {'error': 'Email already registered'}, 400
        
        # First user is admin
        is_admin = User.query.count() == 0
        
        # Create new user
        try:
            user = User(username=username, email=email, is_admin=is_admin)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            
            return {
                'success': True,
                'message': 'User registered successfully',
                'user': user.to_dict(),
                'is_first_user': is_admin
            }, 201
        except ValueError as e:
            return {'error': str(e)}, 400
        except Exception as e:
            db.session.rollback()
            return {'error': f'Registration failed: {str(e)}'}, 500
    
    except Exception as e:
        return {'error': f'Server error: {str(e)}'}, 500


@auth_bp.route('/login', methods=['POST'])
def login():
    """Login a user"""
    try:
        data = request.get_json()
        
        if not data or not data.get('username') or not data.get('password'):
            return {'error': 'Missing username or password'}, 400
        
        username = data.get('username', '').strip()
        password = data.get('password', '')
        
        # Find user
        user = User.query.filter_by(username=username).first()
        
        if not user or not user.check_password(password):
            return {'error': 'Invalid username or password'}, 401
        
        if not user.is_active:
            return {'error': 'User account is disabled'}, 403
        
        # Login user
        login_user(user, remember=True)
        
        return {
            'success': True,
            'message': 'Logged in successfully',
            'user': user.to_dict()
        }, 200
    
    except Exception as e:
        return {'error': f'Login failed: {str(e)}'}, 500


@auth_bp.route('/logout', methods=['POST'])
@login_required
def logout():
    """Logout the current user"""
    try:
        logout_user()
        return {'success': True, 'message': 'Logged out successfully'}, 200
    except Exception as e:
        return {'error': f'Logout failed: {str(e)}'}, 500


@auth_bp.route('/me', methods=['GET'])
@login_required
def get_current_user():
    """Get current user info"""
    try:
        return current_user.to_dict(), 200
    except Exception as e:
        return {'error': f'Error fetching user: {str(e)}'}, 500


@auth_bp.route('/change-password', methods=['POST'])
@login_required
def change_password():
    """Change password for current user"""
    try:
        data = request.get_json()
        
        if not data or not data.get('current_password') or not data.get('new_password'):
            return {'error': 'Missing current or new password'}, 400
        
        current_password = data.get('current_password', '')
        new_password = data.get('new_password', '')
        
        # Verify current password
        if not current_user.check_password(current_password):
            return {'error': 'Current password is incorrect'}, 401
        
        # Validate new password
        if len(new_password) < 8:
            return {'error': 'New password must be at least 8 characters'}, 400
        
        if current_password == new_password:
            return {'error': 'New password must be different from current password'}, 400
        
        # Update password
        try:
            current_user.set_password(new_password)
            db.session.commit()
            return {'success': True, 'message': 'Password changed successfully'}, 200
        except ValueError as e:
            return {'error': str(e)}, 400
    
    except Exception as e:
        db.session.rollback()
        return {'error': f'Error changing password: {str(e)}'}, 500


@auth_bp.route('/health', methods=['GET'])
def auth_health():
    """Check if user is authenticated"""
    return {
        'authenticated': current_user.is_authenticated,
        'user': current_user.to_dict() if current_user.is_authenticated else None
    }, 200


# ============================================================================
# Admin User Management Routes
# ============================================================================

@auth_bp.route('/admin/users', methods=['GET'])
@login_required
@admin_required
def get_all_users():
    """Get all users (admin only)"""
    try:
        users = User.query.all()
        return {
            'success': True,
            'users': [user.to_dict() for user in users],
            'total': len(users)
        }, 200
    except Exception as e:
        return {'error': f'Error fetching users: {str(e)}'}, 500


@auth_bp.route('/admin/users', methods=['POST'])
@login_required
@admin_required
def admin_create_user():
    """Create new user (admin only)"""
    try:
        data = request.get_json()
        
        if not data or not data.get('username') or not data.get('email') or not data.get('password'):
            return {'error': 'Missing required fields (username, email, password)'}, 400
        
        username = data.get('username', '').strip()
        email = data.get('email', '').strip()
        password = data.get('password', '')
        is_admin = data.get('is_admin', False)
        
        # Validate
        if len(username) < 3:
            return {'error': 'Username must be at least 3 characters'}, 400
        
        if '@' not in email:
            return {'error': 'Invalid email address'}, 400
        
        if User.query.filter_by(username=username).first():
            return {'error': 'Username already exists'}, 400
        
        if User.query.filter_by(email=email).first():
            return {'error': 'Email already registered'}, 400
        
        try:
            user = User(username=username, email=email, is_admin=is_admin, is_active=True)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            
            return {
                'success': True,
                'message': 'User created successfully',
                'user': user.to_dict()
            }, 201
        except ValueError as e:
            return {'error': str(e)}, 400
        except Exception as e:
            db.session.rollback()
            return {'error': f'Error creating user: {str(e)}'}, 500
    
    except Exception as e:
        return {'error': f'Server error: {str(e)}'}, 500


@auth_bp.route('/admin/users/<int:user_id>', methods=['GET'])
@login_required
@admin_required
def get_user_by_id(user_id):
    """Get specific user by ID (admin only)"""
    try:
        user = User.query.get(user_id)
        if not user:
            return {'error': 'User not found'}, 404
        
        return user.to_dict(), 200
    except Exception as e:
        return {'error': f'Error fetching user: {str(e)}'}, 500


@auth_bp.route('/admin/users/<int:user_id>', methods=['PUT'])
@login_required
@admin_required
def admin_update_user(user_id):
    """Update user (admin only)"""
    try:
        user = User.query.get(user_id)
        if not user:
            return {'error': 'User not found'}, 404
        
        # Prevent deleting the last admin
        data = request.get_json()
        if not data:
            return {'error': 'No data provided'}, 400
        
        # Update email if provided
        if 'email' in data:
            new_email = data['email'].strip()
            if new_email != user.email and User.query.filter_by(email=new_email).first():
                return {'error': 'Email already in use'}, 400
            user.email = new_email
        
        # Update admin status
        if 'is_admin' in data:
            new_is_admin = data['is_admin']
            # Prevent removing admin status from last admin
            if user.is_admin and not new_is_admin:
                admin_count = User.query.filter_by(is_admin=True).count()
                if admin_count == 1:
                    return {'error': 'Cannot remove admin status from the last admin'}, 400
            user.is_admin = new_is_admin
        
        # Update active status
        if 'is_active' in data:
            user.is_active = data['is_active']
        
        # Update password if provided
        if 'password' in data and data['password']:
            try:
                user.set_password(data['password'])
            except ValueError as e:
                return {'error': str(e)}, 400
        
        db.session.commit()
        
        return {
            'success': True,
            'message': 'User updated successfully',
            'user': user.to_dict()
        }, 200
    
    except Exception as e:
        db.session.rollback()
        return {'error': f'Error updating user: {str(e)}'}, 500


@auth_bp.route('/admin/users/<int:user_id>', methods=['DELETE'])
@login_required
@admin_required
def admin_delete_user(user_id):
    """Delete user (admin only)"""
    try:
        # Prevent deleting yourself
        if user_id == current_user.id:
            return {'error': 'Cannot delete your own account'}, 400
        
        user = User.query.get(user_id)
        if not user:
            return {'error': 'User not found'}, 404
        
        # Prevent deleting last admin
        if user.is_admin:
            admin_count = User.query.filter_by(is_admin=True).count()
            if admin_count == 1:
                return {'error': 'Cannot delete the last admin user'}, 400
        
        db.session.delete(user)
        db.session.commit()
        
        return {
            'success': True,
            'message': 'User deleted successfully'
        }, 200
    
    except Exception as e:
        db.session.rollback()
        return {'error': f'Error deleting user: {str(e)}'}, 500


@auth_bp.route('/admin/users/<int:user_id>/toggle-admin', methods=['POST'])
@login_required
@admin_required
def toggle_admin_status(user_id):
    """Toggle admin status for a user"""
    try:
        user = User.query.get(user_id)
        if not user:
            return {'error': 'User not found'}, 404
        
        # Prevent removing admin status from last admin
        if user.is_admin:
            admin_count = User.query.filter_by(is_admin=True).count()
            if admin_count == 1:
                return {'error': 'Cannot remove admin status from the last admin'}, 400
        
        user.is_admin = not user.is_admin
        db.session.commit()
        
        return {
            'success': True,
            'message': f'User admin status updated to {user.is_admin}',
            'user': user.to_dict()
        }, 200
    
    except Exception as e:
        db.session.rollback()
        return {'error': f'Error updating user: {str(e)}'}, 500


@auth_bp.route('/admin/users/<int:user_id>/toggle-active', methods=['POST'])
@login_required
@admin_required
def toggle_active_status(user_id):
    """Toggle active status for a user"""
    try:
        # Prevent deactivating yourself
        if user_id == current_user.id:
            return {'error': 'Cannot deactivate your own account'}, 400
        
        user = User.query.get(user_id)
        if not user:
            return {'error': 'User not found'}, 404
        
        user.is_active = not user.is_active
        db.session.commit()
        
        return {
            'success': True,
            'message': f'User active status updated to {user.is_active}',
            'user': user.to_dict()
        }, 200
    
    except Exception as e:
        db.session.rollback()
        return {'error': f'Error updating user: {str(e)}'}, 500

