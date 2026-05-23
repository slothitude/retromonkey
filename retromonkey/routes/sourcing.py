"""Sourcing API routes — research, suppliers, RFQ, reorder, quality, business plans."""

from flask import Blueprint, request, jsonify, current_app
from retromonkey.app import db

sourcing_bp = Blueprint("sourcing", __name__)


# =====================================================================
# Market Research
# =====================================================================

@sourcing_bp.route("/research", methods=["POST"])
def research_niche():
    """POST /api/sourcing/research — Full niche research pipeline.

    Body: {"niche": "keyword", "depth": "quick|standard|deep"}
    """
    data = request.json or {}
    niche = data.get("niche")
    if not niche:
        return jsonify({"error": "niche is required"}), 400

    depth = data.get("depth", "standard")

    from retromonkey.services.research import ResearchService
    svc = ResearchService(db)
    result = svc.research_niche(niche, depth)
    return jsonify(result)


# =====================================================================
# Suppliers
# =====================================================================

@sourcing_bp.route("/suppliers")
def list_suppliers():
    """GET /api/sourcing/suppliers — List all suppliers with optional filter."""
    from retromonkey.models.supplier import Supplier

    query = db.session.query(Supplier)
    platform = request.args.get("platform")
    if platform:
        query = query.filter_by(platform=platform)
    trade_assurance = request.args.get("trade_assurance")
    if trade_assurance == "true":
        query = query.filter_by(trade_assurance=True)

    suppliers = query.order_by(Supplier.rating.desc().nullslast()).all()
    return jsonify({
        "items": [{
            "id": s.id,
            "name": s.name,
            "platform": s.platform,
            "url": s.url,
            "rating": s.rating,
            "trade_assurance": s.trade_assurance,
            "min_order_qty": s.min_order_qty,
            "verified": s.verified,
        } for s in suppliers],
    })


@sourcing_bp.route("/suppliers/search", methods=["POST"])
def search_suppliers():
    """POST /api/sourcing/suppliers/search — Search Alibaba for suppliers.

    Body: {"keyword": "usb cable", "filters": {"min_moq": 10, "trade_assurance": true}}
    """
    data = request.json or {}
    keyword = data.get("keyword")
    if not keyword:
        return jsonify({"error": "keyword is required"}), 400

    filters = data.get("filters", {})

    from retromonkey.services.sourcing import SourcingService
    svc = SourcingService(db)
    results = svc.search_suppliers(keyword, filters)
    return jsonify({"suppliers": results})


# =====================================================================
# RFQ
# =====================================================================

@sourcing_bp.route("/rfq", methods=["POST"])
def create_rfq():
    """POST /api/sourcing/rfq — Send RFQs to suppliers.

    Body: {
        "product_id": 1,
        "supplier_ids": [1, 2, 3],
        "target_qty": 100,
        "target_price": 12.50
    }
    """
    data = request.json or {}
    product_id = data.get("product_id")
    supplier_ids = data.get("supplier_ids", [])
    target_qty = data.get("target_qty")
    target_price = data.get("target_price")

    if not product_id or not supplier_ids or not target_qty:
        return jsonify({"error": "product_id, supplier_ids, and target_qty are required"}), 400

    from retromonkey.services.rfq import RFQService
    svc = RFQService(db)
    try:
        results = svc.send_rfq(product_id, supplier_ids, target_qty, target_price)
        return jsonify({"rfqs": results}), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 404


@sourcing_bp.route("/rfq/<int:rfq_id>/responses")
def get_rfq_responses(rfq_id):
    """GET /api/sourcing/rfq/<id>/responses — Get RFQ with response data."""
    from retromonkey.models.supplier import RFQ, Supplier

    rfq = db.session.get(RFQ, rfq_id)
    if not rfq:
        return jsonify({"error": "RFQ not found"}), 404

    supplier = db.session.get(Supplier, rfq.supplier_id)

    return jsonify({
        "rfq_id": rfq.id,
        "product_id": rfq.product_id,
        "supplier": {"id": supplier.id, "name": supplier.name} if supplier else None,
        "status": rfq.status,
        "target_qty": rfq.target_qty,
        "target_price_range": rfq.target_price_range,
        "specifications": rfq.specifications,
        "sent_at": rfq.sent_at.isoformat() if rfq.sent_at else None,
        "response_at": rfq.response_at.isoformat() if rfq.response_at else None,
        "response_data": rfq.response_data,
    })


@sourcing_bp.route("/rfq/<int:product_id>/compare")
def compare_rfq_responses(product_id):
    """GET /api/sourcing/rfq/<product_id>/compare — Compare all RFQ responses for a product."""
    from retromonkey.services.rfq import RFQService
    svc = RFQService(db)
    result = svc.compare_rfq_responses(product_id)
    return jsonify(result)


@sourcing_bp.route("/rfq/<int:rfq_id>/respond", methods=["POST"])
def record_rfq_response(rfq_id):
    """POST /api/sourcing/rfq/<id>/respond — Record a supplier's RFQ response.

    Body: {
        "unit_price": 10.50,
        "moq": 50,
        "lead_time_days": 14,
        "sample_available": true,
        "payment_terms": "30% deposit",
        "notes": "Can offer discount for 500+ units"
    }
    """
    data = request.json or {}
    from retromonkey.services.rfq import RFQService
    svc = RFQService(db)

    try:
        result = svc.record_response(rfq_id, data)
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404


# =====================================================================
# Reorder
# =====================================================================

@sourcing_bp.route("/reorder", methods=["POST"])
def create_reorder():
    """POST /api/sourcing/reorder — Create a purchase order for restocking.

    Body: {
        "product_id": 1,
        "supplier_id": 2,
        "qty": 100,
        "unit_cost": 8.50
    }
    """
    data = request.json or {}
    product_id = data.get("product_id")
    supplier_id = data.get("supplier_id")
    qty = data.get("qty")
    unit_cost = data.get("unit_cost")

    if not all([product_id, supplier_id, qty, unit_cost is not None]):
        return jsonify({"error": "product_id, supplier_id, qty, and unit_cost are required"}), 400

    from retromonkey.services.reorder import ReorderService
    svc = ReorderService(db)

    try:
        result = svc.create_reorder(product_id, supplier_id, qty, unit_cost)
        return jsonify(result), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 404


@sourcing_bp.route("/reorder/check")
def check_reorder_needs():
    """GET /api/sourcing/reorder/check — Find products that need reordering."""
    from retromonkey.services.reorder import ReorderService
    svc = ReorderService(db)
    results = svc.check_reorder_needs()
    return jsonify({"items": results})


@sourcing_bp.route("/reorder/<int:po_id>/receive", methods=["POST"])
def receive_shipment(po_id):
    """POST /api/sourcing/reorder/<po_id>/receive — Mark PO as received.

    Body: {"actual_qty": 98}  (optional, defaults to PO qty)
    """
    data = request.json or {}
    actual_qty = data.get("actual_qty")

    from retromonkey.services.reorder import ReorderService
    svc = ReorderService(db)

    try:
        result = svc.receive_shipment(po_id, actual_qty)
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404


# =====================================================================
# Quality
# =====================================================================

@sourcing_bp.route("/quality")
def get_quality():
    """GET /api/sourcing/quality — Get quality data for a supplier or flagged list.

    Query params:
      - supplier_id: get quality for specific supplier
      - flagged: "true" to get all flagged suppliers
    """
    supplier_id = request.args.get("supplier_id", type=int)
    flagged = request.args.get("flagged") == "true"

    from retromonkey.services.quality import QualityService
    svc = QualityService(db)

    if supplier_id:
        result = svc.get_supplier_quality(supplier_id)
        return jsonify(result)
    elif flagged:
        result = svc.get_flagged_suppliers()
        return jsonify({"flagged": result})
    else:
        return jsonify({"error": "Provide supplier_id or flagged=true"}), 400


@sourcing_bp.route("/quality/log", methods=["POST"])
def log_quality():
    """POST /api/sourcing/quality/log — Log a batch quality assessment.

    Body: {
        "supplier_id": 1,
        "po_id": 5,
        "defect_rate": 2.5,
        "delivery_on_time": 95.0,
        "packaging_quality": 85.0,
        "communication_rating": 90.0,
        "notes": "Good batch, minor packaging issues"
    }
    """
    data = request.json or {}
    supplier_id = data.get("supplier_id")
    if not supplier_id:
        return jsonify({"error": "supplier_id is required"}), 400

    from retromonkey.services.quality import QualityService
    svc = QualityService(db)

    try:
        result = svc.log_batch_quality(
            supplier_id=supplier_id,
            po_id=data.get("po_id"),
            defect_rate=data.get("defect_rate", 0.0),
            delivery_on_time=data.get("delivery_on_time", 100.0),
            packaging_quality=data.get("packaging_quality", 80.0),
            communication_rating=data.get("communication_rating", 80.0),
            notes=data.get("notes"),
        )
        return jsonify(result), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 404


# =====================================================================
# Business Plan
# =====================================================================

@sourcing_bp.route("/business-plan", methods=["POST"])
def generate_business_plan():
    """POST /api/sourcing/business-plan — Generate a full business plan.

    Body: {"niche": "retro gaming accessories", "investment_budget": 5000}
    """
    data = request.json or {}
    niche = data.get("niche")
    budget = data.get("investment_budget")

    if not niche or budget is None:
        return jsonify({"error": "niche and investment_budget are required"}), 400

    from retromonkey.services.business_planner import BusinessPlannerService
    svc = BusinessPlannerService(db)
    result = svc.generate_plan(niche, float(budget))
    return jsonify(result)
