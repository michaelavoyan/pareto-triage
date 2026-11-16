from flask import Blueprint

bp = Blueprint('shop', __name__)
bp.add_url_rule('/cart', view_func=cart)
