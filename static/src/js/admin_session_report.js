/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { Navbar } from "@point_of_sale/app/navbar/navbar";
import { ClosePosPopup } from "@point_of_sale/app/navbar/closing_popup/closing_popup";
import { handleSaleDetails } from "@point_of_sale/app/navbar/sale_details_button/sale_details_button";

/**
 * Core's "Print Report" (session sales details) is gated on
 * `hardwareProxy.printer`, which is only set when the POS is configured to
 * print via an ePOS/IoT Box proxy (`iface_print_via_proxy`). Plain
 * USB-connected printers go through the browser print dialog instead, so
 * the button never appears for them even though printing the report the
 * same way the receipt/bill already print would work fine.
 */

/**
 * Wraps the generic `printer` service (browser print dialog, used by
 * USB-connected printers) in the `{ printer: { printReceipt } }` shape
 * `handleSaleDetails` expects from `hardwareProxy`.
 */
function asHardwareProxy(printerService) {
    return {
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
}

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
        await handleSaleDetails(this.pos, asHardwareProxy(this.printer), this.dialog);
    },
});

/**
 * Auto-print the session sales details report the moment the register is
 * closed, so the report doesn't depend on someone remembering to click
 * "Print Report" first. Printed before the actual close RPC (rather than
 * after) since a successful close immediately reloads the page, which would
 * otherwise race with - and likely cut off - the print.
 */
patch(ClosePosPopup.prototype, {
    setup() {
        super.setup(...arguments);
        this.printer = useService("printer");
    },

    get canPrintSessionReport() {
        return !this.pos.config.module_pos_hr || this.pos.employeeIsAdmin;
    },

    async closeSession() {
        if (this.canPrintSessionReport) {
            const proxy = this.hardwareProxy.printer
                ? this.hardwareProxy
                : asHardwareProxy(this.printer);
            try {
                await handleSaleDetails(this.pos, proxy, this.dialog);
            } catch (error) {
                console.warn("Auto-print of the session report failed", error);
            }
        }
        await super.closeSession(...arguments);
    },
});
