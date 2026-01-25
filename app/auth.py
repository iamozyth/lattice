"""
Authentication routes for NetDoc IPAM
"""
from flask import request
from flask_login import login_user, logout_user, login_required, current_user
from flask_openapi3 import APIBlueprint, Tag
from pydantic import BaseModel, EmailStr, Field
from app import db
from app.models import User
from functools import wraps
import os
import re

auth_bp = APIBlueprint('auth', __name__, url_prefix='/api/auth')

# ============================================================================
# API Tags for Swagger Organization
# ============================================================================
tag_auth = Tag(name='Authentication', description='User authentication and management')

# ============================================================================
# Password Strength Checker
# ============================================================================
def check_password_strength(password: str):
    """
    Analyze password strength and return detailed feedback
    Returns: (strength_score, feedback_dict)
    """
    feedback = {
        'score': 0,
        'strength': 'Very Weak',
        'color': '#ef4444',
        'message': '🤦 Come on, that\'s weaker than my WiFi password!',
        'requirements': {
            'length': len(password) >= 8,
            'uppercase': bool(re.search(r'[A-Z]', password)),
            'lowercase': bool(re.search(r'[a-z]', password)),
            'numbers': bool(re.search(r'\d', password)),
            'special': bool(re.search(r'[!@#$%^&*()_+\-=\[\]{};:\'",.<>?/`~\\|]', password))
        }
    }
    
    # Calculate score
    score = sum([
        min(len(password) // 4, 2),  # Max 2 points for length
        2 if feedback['requirements']['uppercase'] else 0,
        2 if feedback['requirements']['lowercase'] else 0,
        2 if feedback['requirements']['numbers'] else 0,
        2 if feedback['requirements']['special'] else 0
    ])
    
    feedback['score'] = score
    
    # Assign strength levels with funny messages
    if score < 2:
        feedback['strength'] = 'Very Weak'
        feedback['color'] = '#ef4444'
        feedback['message'] = '🤦 Come on, that\'s weaker than my WiFi password!'
    elif score < 4:
        feedback['strength'] = 'Weak'
        feedback['color'] = '#f97316'
        feedback['message'] = '😴 Even my password manager is sleeping...'
    elif score < 6:
        feedback['strength'] = 'Fair'
        feedback['color'] = '#eab308'
        feedback['message'] = '🤔 Getting warmer, but I\'ve cracked easier ones'
    elif score < 8:
        feedback['strength'] = 'Good'
        feedback['color'] = '#84cc16'
        feedback['message'] = '👍 Now we\'re talking! Almost there!'
    elif score < 10:
        feedback['strength'] = 'Strong'
        feedback['color'] = '#22c55e'
        feedback['message'] = '💪 Very nice! Even hackers are impressed!'
    else:
        feedback['strength'] = 'Very Strong'
        feedback['color'] = '#059669'
        feedback['message'] = '🔐 NSA-approved! You\'re basically a security expert now!'
    
    return score, feedback


# ============================================================================
# Pydantic Models for Request/Response Validation
# ============================================================================

class SetupStatusResponse(BaseModel):
    needs_setup: bool
    user_count: int

class SetupRequest(BaseModel):
    username: str = Field(..., min_length=3, description="Username (min 3 chars)")
    email: EmailStr = Field(..., description="Valid email address")
    password: str = Field(..., min_length=8, description="Password (min 8 chars)")

class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    is_admin: bool
    is_active: bool

class SetupResponse(BaseModel):
    message: str
    user: UserResponse

class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)

class LoginResponse(BaseModel):
    success: bool
    message: str
    user: dict

class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3)
    email: EmailStr = Field(...)
    password: str = Field(..., min_length=8)

class RegisterResponse(BaseModel):
    success: bool
    message: str
    user: dict
    is_first_user: bool

class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8)

class PasswordRequirement(BaseModel):
    length: bool
    uppercase: bool
    lowercase: bool
    numbers: bool
    special: bool

class PasswordStrengthResponse(BaseModel):
    score: int
    strength: str
    color: str
    message: str
    requirements: PasswordRequirement

class ErrorResponse(BaseModel):
    authenticated: bool
    user: dict = None

class GetUsersResponse(BaseModel):
    success: bool
    users: list
    total: int

class CreateUserRequest(BaseModel):
    username: str = Field(..., min_length=3)
    email: EmailStr = Field(...)
    password: str = Field(..., min_length=8)
    is_admin: bool = False

class CreateUserResponse(BaseModel):
    success: bool
    message: str
    user: dict

class UpdateUserRequest(BaseModel):
    email: str = None
    is_admin: bool = None
    is_active: bool = None
    password: str = None

class UpdateUserResponse(BaseModel):
    success: bool
    message: str
    user: dict

class ToggleResponse(BaseModel):
    success: bool
    message: str
    user: dict

class ErrorResponse(BaseModel):
    error: str

class MessageResponse(BaseModel):
    success: bool
    message: str

class AuthHealthResponse(BaseModel):
    authenticated: bool
    user: dict = None

# ============================================================================
# Helper Functions
# ============================================================================

def admin_required(f):
    """Decorator to require admin role"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            return {'error': 'Admin access required'}, 403
        return f(*args, **kwargs)
    return decorated_function


@auth_bp.get('/setup-status', tags=[tag_auth],
    responses={"200": SetupStatusResponse, "500": ErrorResponse}
)
def setup_status():
    """Check if system needs initial setup"""
    try:
        user_count = User.query.count()
        return {
            'needs_setup': user_count == 0,
            'user_count': user_count
        }, 200
    except Exception as e:
        return {'error': f'Database error: {str(e)}'}, 500


class CheckPasswordRequest(BaseModel):
    password: str = Field(..., min_length=1, description="Password to check")


@auth_bp.post('/check-password', tags=[tag_auth],
    responses={"200": PasswordStrengthResponse}
)
def check_password(body: CheckPasswordRequest):
    """Check password strength and get feedback"""
    try:
        score, feedback = check_password_strength(body.password)
        return feedback, 200
    except Exception as e:
        return {'error': f'Error checking password: {str(e)}'}, 500


@auth_bp.post('/setup', tags=[tag_auth],
    responses={"201": SetupResponse, "400": ErrorResponse, "403": ErrorResponse, "500": ErrorResponse}
)
def setup(body: SetupRequest):
    """Initialize system with first admin user"""
    try:
        # Check if system is already set up
        if User.query.count() > 0:
            return {'error': 'System is already set up'}, 403
        
        username = body.username.strip()
        email = body.email.strip()
        password = body.password
        
        # Create first admin user
        user = User(
            username=username,
            email=email,
            is_admin=True,
            is_active=True
        )
        user.set_password(password)
        
        db.session.add(user)
        db.session.commit()
        
        # Auto-login the first admin user after setup
        login_user(user, remember=True)
        
        return {
            'message': 'Admin user created successfully',
            'user': {
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'is_admin': user.is_admin
            }
        }, 201
    
    except Exception as e:
        db.session.rollback()
        return {'error': f'Setup failed: {str(e)}'}, 500


@auth_bp.post('/register', tags=[tag_auth],
    responses={"201": RegisterResponse, "400": ErrorResponse, "500": ErrorResponse}
)
def register(body: RegisterRequest):
    """Register a new user"""
    try:
        username = body.username.strip()
        email = body.email.strip()
        password = body.password
        
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
            
            # Auto-login the user after registration
            login_user(user, remember=True)
            
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


@auth_bp.post('/login', tags=[tag_auth],
    responses={"200": LoginResponse, "400": ErrorResponse, "401": ErrorResponse, "403": ErrorResponse, "500": ErrorResponse}
)
def login(body: LoginRequest):
    """Login a user"""
    try:
        username = body.username.strip()
        password = body.password
        
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


@auth_bp.post('/logout', tags=[tag_auth],
    responses={"200": {"type": "object", "properties": {"success": {"type": "boolean"}, "message": {"type": "string"}}}}
)
@login_required
def logout():
    """Logout the current user"""
    try:
        logout_user()
        return {'success': True, 'message': 'Logged out successfully'}, 200
    except Exception as e:
        return {'error': f'Logout failed: {str(e)}'}, 500


@auth_bp.get('/me', tags=[tag_auth],
    responses={"200": UserResponse}
)
@login_required
def get_current_user():
    """Get current user information"""
    try:
        return current_user.to_dict(), 200
    except Exception as e:
        return {'error': f'Error fetching user: {str(e)}'}, 500


@auth_bp.post('/change-password', tags=[tag_auth],
    responses={"200": {"type": "object", "properties": {"success": {"type": "boolean"}, "message": {"type": "string"}}}, "400": ErrorResponse, "401": ErrorResponse, "500": ErrorResponse}
)
@login_required
def change_password(body: ChangePasswordRequest):
    """Change password for current user"""
    try:
        current_password = body.current_password
        new_password = body.new_password
        
        # Verify current password
        if not current_user.check_password(current_password):
            return {'error': 'Current password is incorrect'}, 401
        
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


@auth_bp.get('/health', tags=[tag_auth],
    responses={"200": AuthHealthResponse}
)
def auth_health():
    """Check if user is authenticated"""
    return {
        'authenticated': current_user.is_authenticated,
        'user': current_user.to_dict() if current_user.is_authenticated else None
    }, 200


# ============================================================================
# Admin User Management Routes
# ============================================================================

@auth_bp.get('/admin/users', tags=[tag_auth],
    responses={"200": GetUsersResponse, "403": ErrorResponse, "500": ErrorResponse}
)
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


@auth_bp.post('/admin/users', tags=[tag_auth],
    responses={"201": CreateUserResponse, "400": ErrorResponse, "403": ErrorResponse, "500": ErrorResponse}
)
@login_required
@admin_required
def admin_create_user(body: CreateUserRequest):
    """Create new user (admin only)"""
    try:
        username = body.username.strip()
        email = body.email.strip()
        password = body.password
        is_admin = body.is_admin
        
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


@auth_bp.get('/admin/users/<int:user_id>', tags=[tag_auth],
    responses={"200": UserResponse, "404": ErrorResponse, "500": ErrorResponse}
)
@login_required
@admin_required
def get_user_by_id(user_id: int):
    """Get specific user by ID (admin only)"""
    try:
        user = User.query.get(user_id)
        if not user:
            return {'error': 'User not found'}, 404
        
        return user.to_dict(), 200
    except Exception as e:
        return {'error': f'Error fetching user: {str(e)}'}, 500


@auth_bp.put('/admin/users/<int:user_id>', tags=[tag_auth],
    responses={"200": UpdateUserResponse, "400": ErrorResponse, "404": ErrorResponse, "500": ErrorResponse}
)
@login_required
@admin_required
def admin_update_user(user_id: int, body: UpdateUserRequest):
    """Update user (admin only)"""
    try:
        user = User.query.get(user_id)
        if not user:
            return {'error': 'User not found'}, 404
        
        # Prevent deleting the last admin
        # Update email if provided
        if body.email:
            new_email = body.email.strip()
            if new_email != user.email and User.query.filter_by(email=new_email).first():
                return {'error': 'Email already in use'}, 400
            user.email = new_email
        
        # Update admin status
        if body.is_admin is not None:
            new_is_admin = body.is_admin
            # Prevent removing admin status from last admin
            if user.is_admin and not new_is_admin:
                admin_count = User.query.filter_by(is_admin=True).count()
                if admin_count == 1:
                    return {'error': 'Cannot remove admin status from the last admin'}, 400
            user.is_admin = new_is_admin
        
        # Update active status
        if body.is_active is not None:
            user.is_active = body.is_active
        
        # Update password if provided
        if body.password:
            try:
                user.set_password(body.password)
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


@auth_bp.delete('/admin/users/<int:user_id>', tags=[tag_auth],
    responses={"200": {"type": "object", "properties": {"success": {"type": "boolean"}, "message": {"type": "string"}}}, "400": ErrorResponse, "404": ErrorResponse, "500": ErrorResponse}
)
@login_required
@admin_required
def admin_delete_user(user_id: int):
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


@auth_bp.post('/admin/users/<int:user_id>/toggle-admin', tags=[tag_auth],
    responses={"200": ToggleResponse, "400": ErrorResponse, "404": ErrorResponse, "500": ErrorResponse}
)
@login_required
@admin_required
def toggle_admin_status(user_id: int):
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


@auth_bp.post('/admin/users/<int:user_id>/toggle-active', tags=[tag_auth],
    responses={"200": ToggleResponse, "400": ErrorResponse, "404": ErrorResponse, "500": ErrorResponse}
)
@login_required
@admin_required
def toggle_active_status(user_id: int):
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


# ============================================================================
# Version and Update Checking
# ============================================================================

@auth_bp.get('/version', tags=[tag_auth])
def get_version():
    """Get current application version"""
    from app import VERSION
    return {
        'version': VERSION,
        'name': 'NetDoc IPAM',
        'repository': 'https://github.com/iamozyth/netdoc-ipam'
    }, 200


@auth_bp.get('/check-updates', tags=[tag_auth])
def check_updates():
    """Check if updates are available on GitHub"""
    try:
        from app import VERSION
        from app.updates import check_for_updates
        
        update_info = check_for_updates(VERSION)
        return update_info, 200
    except ImportError:
        # requests library not available
        return {
            'update_available': False,
            'current_version': '1.0.0-beta.1',
            'latest_version': None,
            'release_url': None,
            'release_notes': None,
            'published_at': None,
            'is_prerelease': False,
            'error': 'Update checking not available (requests library not installed)'
        }, 200
    except Exception as e:
        return {
            'update_available': False,
            'current_version': '1.0.0-beta.1',
            'error': f'Error checking for updates: {str(e)}'
        }, 200
