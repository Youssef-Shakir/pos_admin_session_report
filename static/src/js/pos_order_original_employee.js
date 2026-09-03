/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { PosOrder } from "@point_of_sale/app/models/pos_order";

/**
 * Track the original employee who created/took the order.
 * Captures the employee when the first product is added to the order.
 */
patch(PosOrder.prototype, {
    addOrderline(line) {
        // Capture the original employee only once - when the first line is added
        if (!this.x_original_employee_id && this.lines && this.lines.length === 0) {
            try {
                if (this.pos && typeof this.pos.get_cashier === 'function') {
                    const cashier = this.pos.get_cashier();
                    if (cashier && cashier.id) {
                        this.x_original_employee_id = cashier.id;
                    }
                }
            } catch (e) {
                // Ignore errors
            }
        }
        return super.addOrderline(...arguments);
    },
});
