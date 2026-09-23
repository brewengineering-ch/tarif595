const form = document.querySelector("#document-form");
const statusMessage = form.querySelector(".status");
const downloadLink = form.querySelector(".download-link");
const buttons = form.querySelectorAll("button");

const formValues = () => Object.fromEntries(new FormData(form).entries());

const addressPayload = (data, prefix) => ({
  street: data[`${prefix}_street`],
  house_number: data[`${prefix}_house_number`],
  postal_code: data[`${prefix}_postal_code`],
  city: data[`${prefix}_city`],
});

const partyPayload = (data, prefix) => ({
  ...addressPayload(data, prefix),
  name: data[`${prefix}_name`],
  country_code: data[`${prefix}_country_code`],
});

const companyPayload = (data, prefix) => ({
  ...addressPayload(data, prefix),
  name: data[`${prefix}_name`],
});

const qrPayload = (data) => ({
  account: data.account,
  creditor: partyPayload(data, "creditor"),
  debtor: partyPayload(data, "debtor"),
  amount: data.amount,
  currency: data.currency,
  reference: data.reference,
  message: data.message,
  bill_information: data.bill_information,
  invoice_number: data.invoice_number,
  invoice_date: data.invoice_date,
  service_description: data.service_name,
  service_date_begin: data.service_date_begin,
  service_date_end: data.service_date_end,
  service_quantity: data.service_quantity,
  service_unit_price: data.service_unit_price,
});

const tarifPayload = (data) => ({
  qr_bill: qrPayload(data),
  invoice_number: data.invoice_number,
  invoice_date: data.invoice_date,
  provider_gln: data.provider_gln,
  provider_location_gln: data.provider_location_gln,
  provider_zsr: data.provider_zsr || null,
  insurer_gln: data.insurer_gln,
  insurer: companyPayload(data, "insurer"),
  patient: {
    ...addressPayload(data, "patient"),
    given_name: data.patient_given_name,
    family_name: data.patient_family_name,
    gender: data.patient_gender,
    birthdate: data.patient_birthdate,
    ssn: data.patient_ssn,
  },
  canton: data.canton,
  service: {
    code: data.service_code,
    name: data.service_name,
    date_begin: data.service_date_begin,
    date_end: data.service_date_end,
    quantity: data.service_quantity,
    unit_price: data.service_unit_price,
    vat_rate: data.service_vat_rate,
  },
  notes: data.notes,
});

const validateSections = (includeTarif) => {
  const selectors = includeTarif ? ["#qr-section", "#tarif-section"] : ["#qr-section"];
  for (const selector of selectors) {
    const fields = form.querySelectorAll(`${selector} input, ${selector} select, ${selector} textarea`);
    for (const field of fields) {
      if (!field.checkValidity()) {
        field.reportValidity();
        return false;
      }
    }
  }
  return true;
};

const setButtonsDisabled = (disabled) => {
  buttons.forEach((button) => {
    button.disabled = disabled;
  });
};

const errorMessage = async (response) => {
  const payload = await response.json().catch(() => null);
  return JSON.stringify(payload?.detail ?? payload ?? response.statusText);
};

const prepareDownload = (blob, filename) => {
  if (downloadLink.dataset.objectUrl) {
    URL.revokeObjectURL(downloadLink.dataset.objectUrl);
  }

  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = filename;
  link.click();

  downloadLink.href = objectUrl;
  downloadLink.download = filename;
  downloadLink.textContent = `Download ${filename} again`;
  downloadLink.dataset.objectUrl = objectUrl;
  downloadLink.hidden = false;
};

form.querySelectorAll("button[data-endpoint]").forEach((button) => {
  button.addEventListener("click", async () => {
    const isTarif = button.dataset.payload === "tarif";
    if (!validateSections(isTarif)) {
      return;
    }

    downloadLink.hidden = true;
    statusMessage.textContent = "Generating PDF...";
    setButtonsDisabled(true);

    try {
      const data = formValues();
      const response = await fetch(button.dataset.endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(isTarif ? tarifPayload(data) : qrPayload(data)),
      });
      if (!response.ok) {
        throw new Error(await errorMessage(response));
      }

      prepareDownload(await response.blob(), button.dataset.filename);
      statusMessage.textContent = "PDF ready.";
    } catch (error) {
      statusMessage.textContent = `Request failed: ${error.message}`;
    } finally {
      setButtonsDisabled(false);
    }
  });
});
