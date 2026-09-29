/** Trim only. Leading zeros are part of the identifier and must stay. */
const EAN_LENGTHS = new Set([8, 12, 13]);
export function prepareBarcode(raw) {
    const code = String(raw ?? "").trim();
    if (!code)
        return { code: "", error: "Enter a barcode, or scan it again." };
    if (code.length > 80)
        return { code, error: "That code is too long to be a package barcode. Scan the package barcode, or type it." };
    if (/[^\x20-\x7E]/.test(code))
        return { code, error: "That barcode contains characters this desk cannot use. Scan again or type the digits." };
    if (/^\d+$/.test(code) && EAN_LENGTHS.has(code.length) && !eanCheck(code)) {
        const kind = code.length === 13 ? "EAN-13" : code.length === 12 ? "UPC-A" : "EAN-8";
        return { code, error: `That is not a valid ${kind}. Check every digit, including leading zeros.` };
    }
    return { code, error: "" };
}
export function eanCheck(digits) {
    if (!/^\d+$/.test(digits) || digits.length < 2)
        return false;
    const body = digits.slice(0, -1);
    const expected = Number(digits.slice(-1));
    let sum = 0;
    for (let i = 0; i < body.length; i++) {
        const fromRight = body.length - 1 - i;
        const weight = fromRight % 2 === 0 ? 3 : 1;
        sum += Number(body[i]) * weight;
    }
    return (10 - (sum % 10)) % 10 === expected;
}
export function formatAllowed(format, allowed) {
    return allowed.includes(format);
}
