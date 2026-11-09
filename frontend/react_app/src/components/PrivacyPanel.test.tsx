import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { PrivacyPanel } from "./PrivacyPanel";
import { api } from "@/lib/api";

describe("PrivacyPanel", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("downloads the export as a JSON file", async () => {
    const exportData = vi.spyOn(api, "exportData").mockResolvedValue({ data: { users: [] } });
    const createUrl = vi.fn(() => "blob:x");
    const revokeUrl = vi.fn();
    Object.assign(URL, { createObjectURL: createUrl, revokeObjectURL: revokeUrl });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    render(<PrivacyPanel token="t" onDeleted={() => {}} />);
    fireEvent.click(screen.getByText("Download my data"));

    await waitFor(() => expect(click).toHaveBeenCalled());
    expect(exportData).toHaveBeenCalledWith("t");
    expect(revokeUrl).toHaveBeenCalledWith("blob:x");
  });

  it("deletes only after the confirmation word is typed", async () => {
    const deleteData = vi.spyOn(api, "deleteData").mockResolvedValue({ deleted: {} });
    const onDeleted = vi.fn();
    render(<PrivacyPanel token="t" onDeleted={onDeleted} />);

    fireEvent.click(screen.getByText("Delete my account and data…"));
    const confirm = screen.getByText("Delete permanently") as HTMLButtonElement;
    expect(confirm.disabled).toBe(true);

    fireEvent.change(screen.getByLabelText("Type DELETE to confirm"), { target: { value: "delete" } });
    expect(confirm.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Type DELETE to confirm"), { target: { value: "DELETE" } });
    expect(confirm.disabled).toBe(false);

    fireEvent.click(confirm);
    await waitFor(() => expect(onDeleted).toHaveBeenCalled());
    expect(deleteData).toHaveBeenCalledWith("t");
  });

  it("keeps the account and shows the error if deletion fails", async () => {
    vi.spyOn(api, "deleteData").mockRejectedValue(new Error("server down"));
    const onDeleted = vi.fn();
    render(<PrivacyPanel token="t" onDeleted={onDeleted} />);

    fireEvent.click(screen.getByText("Delete my account and data…"));
    fireEvent.change(screen.getByLabelText("Type DELETE to confirm"), { target: { value: "DELETE" } });
    fireEvent.click(screen.getByText("Delete permanently"));

    await waitFor(() => expect(screen.getByRole("alert").textContent).toBe("server down"));
    expect(onDeleted).not.toHaveBeenCalled();
  });
});
