/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { Navbar } from "@point_of_sale/app/navbar/navbar";
import { handleSaleDetails } from "@point_of_sale/app/navbar/sale_details_button/sale_details_button";

/**
 * Core's "Print Report" (session sales details) is gated on
 * `hardwareProxy.printer`, which is only set when the POS is configured to
 * print via an ePOS/IoT Box proxy (`iface_print_via_proxy`). Plain
 * USB-connected printers go through the browser print dialog instead, so
 * the button never appears for them even though printing the report the
 * same way the receipt/bill already print would work fine.
 */
patch(Navbar.prototype, {
    setup() {
        super.setup(...arguments);
        this.printer = useService("printer");
    },

    /**
     * Without Employee Login there is only one person running the POS, so
     * the report stays visible to everyone. With Employee Login, only the
     * currently logged in manager/admin cashier sees it.
     */
    get canPrintSessionReport() {
        return !this.pos.config.module_pos_hr || this.pos.employeeIsAdmin;
    },

    async showSaleDetails() {
        if (this.hardwareProxy.printer) {
            // Proxy-connected printer: unchanged core behavior.
            await super.showSaleDetails(...arguments);
            return;
        }
        // No proxy printer: reuse the same report data/rendering as core,
        // but print it through the generic printer service so it falls
        // back to the browser print dialog (regular USB printers).
        const printerService = this.printer;
        const webPrintProxy = {
            printer: {
                async printReceipt(el) {
                    try {
                        const printed = await printerService.printHtml(el, {
                            webPrintFallback: true,
                        });
                        return { successful: Boolean(printed), message: {} };
                    } catch (error) {
                        return {
                            successful: false,
                            message: { title: error.title, body: error.body },
                        };
                    }
                },
            },
        };
        await handleSaleDetails(this.pos, webPrintProxy, this.dialog);
    },
});
