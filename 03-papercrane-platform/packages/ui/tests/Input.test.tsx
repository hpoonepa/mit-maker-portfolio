import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Input } from "../src/primitives/Input";

describe("Input", () => {
  it("renders with a label associated via htmlFor", () => {
    render(<Input label="Email" id="email-field" />);
    const input = screen.getByLabelText("Email");
    expect(input).toHaveAttribute("id", "email-field");
  });

  it("auto-generates an id when none is provided", () => {
    render(<Input label="Name" />);
    const input = screen.getByLabelText("Name");
    expect(input.id).toBeTruthy();
  });

  it("sets aria-invalid when error is present", () => {
    render(<Input label="Email" error="Required" />);
    const input = screen.getByLabelText("Email");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByText("Required")).toBeInTheDocument();
  });

  it("does not set aria-invalid without error", () => {
    render(<Input label="Email" />);
    const input = screen.getByLabelText("Email");
    expect(input).not.toHaveAttribute("aria-invalid");
  });

  it("accepts type=email and password", () => {
    const { rerender } = render(<Input label="Email" type="email" />);
    expect(screen.getByLabelText("Email")).toHaveAttribute("type", "email");
    rerender(<Input label="Password" type="password" />);
    expect(screen.getByLabelText("Password")).toHaveAttribute("type", "password");
  });

  it("ties error message via aria-describedby", () => {
    render(<Input label="Email" error="Bad input" />);
    const input = screen.getByLabelText("Email");
    const describedBy = input.getAttribute("aria-describedby");
    expect(describedBy).toBeTruthy();
    const err = document.getElementById(describedBy!);
    expect(err).toHaveTextContent("Bad input");
  });

  it("accepts user input", async () => {
    render(<Input label="Q" />);
    const input = screen.getByLabelText("Q") as HTMLInputElement;
    await userEvent.type(input, "hi");
    expect(input.value).toBe("hi");
  });

  it("merges className on the input", () => {
    render(<Input label="Q" className="custom-input" />);
    expect(screen.getByLabelText("Q").className).toContain("custom-input");
  });
});
