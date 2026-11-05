/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { Navbar } from "@point_of_sale/app/navbar/navbar";
import { ClosePosPopup } from "@point_of_sale/app/navbar/closing_popup/closing_popup";
import { renderToElement } from "@web/core/utils/render";
import { handleSaleDetails } from "@point_of_sale/app/navbar/sale_details_button/sale_details_button";
import { SelectionPopup } from "@point_of_sale/app/utils/input_popups/selection_popup";
import { formatDateTime } from "@web/core/l10n/dates";
import { parseFloat } from "@web/views/fields/parsers";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";

const { DateTime } = luxon;

/**
 * Renders and prints the custom session report.
 */
async function printCustomReport(pos, printer, hardwareProxy, templateType, closing = null) {
    // Fetch report data from the server. Orders are synced before (see syncBeforeReport), so the
    // figures are the session's real ones; `closing` adds what the cashier counted when closing.
    const data = await pos.data.call(
        'pos.session',
        'get_custom_session_report_data',
        [pos.session.id],
        { closing: closing }
    );

    if (!data || !data.session_name) {
        console.warn("No report data available");
        return;
    }

    // Format currency helper
    const formatCurrency = (amount) => {
        return pos.env.utils.formatCurrency(amount);
    };

    // Time the report is printed. Prefer the server clock (already shifted to
    // the user's timezone by the backend) so it lines up with the opening
    // date on the same report; fall back to the local clock, formatted the
    // same way the standard Odoo sale details report does.
    const currentDateTime = data.print_date || formatDateTime(DateTime.now());

    // Select template based on type
    const templateName = templateType === 'custom_arabic'
        ? 'pos_admin_session_report.CustomSessionReportArabic'
        : 'pos_admin_session_report.CustomSessionReport';

    // Render the report template
    const reportEl = renderToElement(templateName, {
        data: data,
        formatCurrency: formatCurrency,
        currentDateTime: currentDateTime,
    });

    // Print using hardware proxy or browser print
    if (hardwareProxy && hardwareProxy.printer) {
        await hardwareProxy.printer.printReceipt(reportEl);
    } else if (printer) {
        await printer.printHtml(reportEl, { webPrintFallback: true });
    }
}

/**
 * Wraps the generic `printer` service (browser print dialog, used by
 * USB-connected printers) in the `{ printer: { printReceipt } }` shape.
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

/**
 * Send the orders still waiting on this device before printing: with a poor connection the
 * server would otherwise print old figures. Returns false when they could not be sent.
 */
async function syncBeforeReport(pos, dialog) {
    let synced = false;
    try {
        synced = await pos.push_orders_with_closing_popup();
    } catch (error) {
        console.warn("Session report: orders could not be synced", error);
    }
    if (!synced) {
        dialog.add(AlertDialog, {
            title: "Report not printed",
            body: "Some orders are not sent to the server yet (no or poor internet). " +
                "The report would show old figures. Check the connection and try again.",
        });
    }
    return synced;
}

/**
 * Print report based on template setting
 */
async function printReportByTemplate(pos, printer, hardwareProxy, dialog, templateSetting, closing = null) {
    const proxy = hardwareProxy.printer ? hardwareProxy : asHardwareProxy(printer);

    if (templateSetting === 'standard') {
        await handleSaleDetails(pos, proxy, dialog);
    } else if (templateSetting === 'custom') {
        const printerSvc = hardwareProxy.printer ? null : printer;
        const hwProxy = hardwareProxy.printer ? hardwareProxy : null;
        await printCustomReport(pos, printerSvc, hwProxy, 'custom', closing);
    } else if (templateSetting === 'custom_arabic') {
        const printerSvc = hardwareProxy.printer ? null : printer;
        const hwProxy = hardwareProxy.printer ? hardwareProxy : null;
        await printCustomReport(pos, printerSvc, hwProxy, 'custom_arabic', closing);
    }
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
        const templateSetting = this.pos.config.session_report_template || 'ask';
        if (!(await syncBeforeReport(this.pos, this.dialog))) {
            return;
        }

        // If a default template is set, print directly
        if (templateSetting !== 'ask') {
            await printReportByTemplate(
                this.pos,
                this.printer,
                this.hardwareProxy,
                this.dialog,
                templateSetting
            );
            return;
        }

        // Show selection popup to choose report template
        const self = this;
        this.dialog.add(SelectionPopup, {
            title: "Select Report Template",
            list: [
                { id: 1, label: "Standard Report", item: "standard", isSelected: true },
                { id: 2, label: "Custom Report (English)", item: "custom", isSelected: false },
                { id: 3, label: "Custom Report (Arabic)", item: "custom_arabic", isSelected: false },
            ],
            getPayload: async (selected) => {
                if (!selected) return;
                await printReportByTemplate(
                    self.pos,
                    self.printer,
                    self.hardwareProxy,
                    self.dialog,
                    selected
                );
            },
        });
    },
});

/**
 * Auto-print the session sales details report the moment the register is
 * closed, so the report doesn't depend on someone remembering to click
 * "Print Report" first.
 */
patch(ClosePosPopup.prototype, {
    setup() {
        super.setup(...arguments);
        this.printer = useService("printer");
    },

    get canPrintSessionReport() {
        return !this.pos.config.module_pos_hr || this.pos.employeeIsAdmin;
    },

    /**
     * What the cashier entered in this popup: counted amount per payment method, notes and who
     * closes. Printed on the report as expected / counted / difference.
     */
    _sessionReportClosingDetails() {
        const counted = {};
        const read = (id) => {
            const value = this.state.payments[id]?.counted;
            if (value === undefined || value === null || value === "") {
                return null;
            }
            try {
                return parseFloat(String(value));
            } catch {
                return null;
            }
        };
        if (this.pos.config.cash_control && this.props.default_cash_details) {
            counted[this.props.default_cash_details.id] = read(this.props.default_cash_details.id);
        }
        for (const pm of this.props.non_cash_payment_methods || []) {
            counted[pm.id] = read(pm.id);
        }
        return {
            counted,
            notes: this.state.notes || "",
            closed_by: this.pos.get_cashier()?.name || "",
        };
    },

    async closeSession() {
        if (this.canPrintSessionReport) {
            // Orders first, so the closing report is never printed with old figures. If they can't
            // be sent, the standard closing would stop here anyway.
            if (!(await syncBeforeReport(this.pos, this.dialog))) {
                return;
            }
            const closing = this._sessionReportClosingDetails();
            const templateSetting = this.pos.config.session_report_template || 'ask';

            // If a default template is set, print directly
            if (templateSetting !== 'ask') {
                try {
                    await printReportByTemplate(
                        this.pos,
                        this.printer,
                        this.hardwareProxy,
                        this.dialog,
                        templateSetting,
                        closing
                    );
                } catch (error) {
                    console.warn("Auto-print of the session report failed", error);
                }
            } else {
                // Show selection popup before closing
                const self = this;
                try {
                    await new Promise((resolve) => {
                        this.dialog.add(SelectionPopup, {
                            title: "Select Report Template",
                            list: [
                                { id: 1, label: "Standard Report", item: "standard", isSelected: true },
                                { id: 2, label: "Custom Report (English)", item: "custom", isSelected: false },
                                { id: 3, label: "Custom Report (Arabic)", item: "custom_arabic", isSelected: false },
                                { id: 4, label: "No Report", item: "none", isSelected: false },
                            ],
                            getPayload: async (selected) => {
                                if (selected && selected !== "none") {
                                    try {
                                        await printReportByTemplate(
                                            self.pos,
                                            self.printer,
                                            self.hardwareProxy,
                                            self.dialog,
                                            selected,
                                            closing
                                        );
                                    } catch (error) {
                                        console.warn("Auto-print of the session report failed", error);
                                    }
                                }
                                resolve();
                            },
                        });
                    });
                } catch (error) {
                    console.warn("Report selection cancelled", error);
                }
            }
        }
        await super.closeSession(...arguments);
    },
});
