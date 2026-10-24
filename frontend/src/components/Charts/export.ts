/** Resolve theme styles so exported SVG is self contained, then rasterize at 2x. */
export async function downloadChartPng(svg: SVGSVGElement, filename: string) {
  const clone = svg.cloneNode(true) as SVGSVGElement;
  const originals = [svg, ...Array.from(svg.querySelectorAll("*"))];
  const copies = [clone, ...Array.from(clone.querySelectorAll("*"))];
  originals.forEach((el, index) => {
    const style = getComputedStyle(el);
    for (const key of [
      "fill",
      "stroke",
      "color",
      "font-family",
      "font-size",
      "font-weight",
      "opacity",
      "stroke-width",
      "stroke-dasharray",
      "stroke-opacity",
      "fill-opacity",
    ]) {
      (copies[index] as SVGElement).style.setProperty(
        key,
        style.getPropertyValue(key),
      );
    }
  });
  const { width, height: visibleHeight, y } = svg.viewBox.baseVal;
  const height = visibleHeight + y;
  clone.setAttribute("viewBox", `0 0 ${width} ${height}`);
  clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  clone.setAttribute("width", String(width));
  clone.setAttribute("height", String(height));
  const url = URL.createObjectURL(
    new Blob([new XMLSerializer().serializeToString(clone)], {
      type: "image/svg+xml;charset=utf-8",
    }),
  );
  try {
    const img = new Image();
    img.src = url;
    await img.decode();
    const canvas = document.createElement("canvas");
    canvas.width = width * 2;
    canvas.height = height * 2;
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("PNG export unavailable");
    ctx.scale(2, 2);
    ctx.fillStyle = getComputedStyle(
      svg.closest("section") || svg,
    ).backgroundColor;
    ctx.fillRect(0, 0, width, height);
    ctx.drawImage(img, 0, 0, width, height);
    const blob = await new Promise<Blob>((resolve, reject) =>
      canvas.toBlob(
        (b) => (b ? resolve(b) : reject(new Error("PNG export failed"))),
        "image/png",
      ),
    );
    const png = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = png;
    a.download = `${filename.replace(/[^a-z0-9_-]/gi, "-").slice(0, 80) || "chart"}.png`;
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(png), 1000);
  } finally {
    URL.revokeObjectURL(url);
  }
}
