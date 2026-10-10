import { t as __exportAll } from "./rolldown-runtime-D7D4PA-g.js";
import { $a as reformIntervals, A as registerPreprocessor, Aa as getPixelPrecision, Ar as getShapeClass, Br as registerShape, Bt as createSymbol, C as registerCoordinateSystem, Cn as getTooltipMarker, D as registerMap, Dn as getTextRect, Dr as extendPath, E as registerLoading, Ea as asc, F as registerVisual, Ga as nice, I as setCanvasCreator, Ia as isRadianAroundZero, In as enableDataStack, Ir as makeImage, Ja as parsePercent, Ka as numericToNumber, Kn as SeriesData, L as version, La as linearMap, Ln as getStackedDimension, Lr as makePath, M as registerTheme, Ma as getPrecisionSafe, N as registerTransform, Nn as registerLocale, O as registerPostInit, On as format, Or as extendShape, P as registerUpdateLifecycle, Pa as isNumeric, Qa as quantityExponent, Ri as getECData, Rn as isDimensionStacked, Rr as mergePath, Rt as ChartView, S as registerAction, Sr as createIcon, T as registerLayout, Tn as toCamelCase, Vr as resizePath, W as ComponentView, Wn as createDimensions, Wt as SeriesModel, Xa as quantile, Xr as initProps, Y as throttle, Za as quantity, _ as getCoordinateSystemDimensions, _n as addCommas, ai as Arc, b as getMap, bn as formatTime, br as clipPointsByRect, c as AxisModelCommonMixin, ci as Polyline, d as connect, di as Sector, ei as updateProps, eo as remRadian, et as Axis, f as dataTool, fi as Ellipse, ft as createScaleByModel, g as dispose, h as disconnect, ii as LinearGradient, j as registerProcessor, ja as getPrecision, jr as getTransform, k as registerPostUpdate, ka as getPercentWithPrecision, kn as roundTime, l as use, li as Polygon, m as disConnect, no as roundLegacy, o as scaleCalcNice2, oi as BezierCurve, or as Model, p as dependencies, pi as Circle, pn as getLayoutRect, pt as determineAxisType, qa as parseDate, ri as RadialGradient, rn as ComponentModel, si as Line, t as parseGeoJSON, ti as IncrementalDisplayable, u as PRIORITY, ui as Ring, ur as createTextStyle$1, v as getInstanceByDom, vi as enableHoverEmphasis, vn as capitalFirst, w as registerCustomSeries, wa as MAX_SAFE_INTEGER, wn as normalizeCssArray, x as init, xn as formatTpl, xr as clipRectByRect, y as getInstanceById } from "./parseGeoJson-BuroNMpY.js";
import { $n as map, C as Group, D as Rect, Hn as isFunction, Jn as isString, Kn as isObject, Ln as indexOf, Lt as BoundingRect, Mt as truncateText, Nn as extend, On as curry, Pn as filter, Rn as inherits, S as CompoundPath, Sn as env, Tn as clone, ar as reduce, cn as vector_exports, er as merge, f as zrender_exports, fr as util_exports$1, gr as setPlatformAPI, j as ZRImage, jn as each, kn as defaults, lt as color_exports, mn as matrix_exports, nr as mixin, r as brushSingle, w as ZRText, wn as bind, y as encodeHTML, zn as isArray } from "./graphic-CKloBv3l.js";
import { t as createSeriesData } from "./createSeriesData-TyZtHZLU.js";
//#region node_modules/echarts/lib/export/api/helper.js
/**
* AUTO-GENERATED FILE. DO NOT MODIFY.
*/
/**
* This module exposes helper functions for developing extensions.
*/
var helper_exports = /* @__PURE__ */ __exportAll({
	createDimensions: () => createDimensions,
	createList: () => createList,
	createScale: () => createScale,
	createSymbol: () => createSymbol,
	createTextStyle: () => createTextStyle,
	dataStack: () => dataStack,
	enableHoverEmphasis: () => enableHoverEmphasis,
	getECData: () => getECData,
	getLayoutRect: () => getLayoutRect,
	mixinAxisModelCommonMethods: () => mixinAxisModelCommonMethods
});
/**
* Create a multi dimension List structure from seriesModel.
*/
function createList(seriesModel) {
	return createSeriesData(null, seriesModel);
}
var dataStack = {
	isDimensionStacked,
	enableDataStack,
	getStackedDimension
};
/**
* Externally used by echarts-gl.
* Create scale
* @param dataExtent
* @param option If `option.type`
*        is specified, it can only be `'value'` currently.
*/
function createScale(dataExtent, option) {
	var axisModel = option;
	if (!(option instanceof Model)) axisModel = new Model(option);
	var axisType = determineAxisType(axisModel);
	var scale = createScaleByModel(axisModel, axisType, false);
	if (dataExtent[1] < dataExtent[0]) dataExtent = dataExtent.slice().reverse();
	scaleCalcNice2(scale, axisModel, null, null, dataExtent);
	return scale;
}
/**
* Mixin common methods to axis model
*/
function mixinAxisModelCommonMethods(Model) {
	mixin(Model, AxisModelCommonMixin);
}
function createTextStyle(textStyleModel, opts) {
	opts = opts || {};
	return createTextStyle$1(textStyleModel, null, null, opts.state !== "normal");
}
//#endregion
//#region node_modules/echarts/lib/export/api/number.js
var number_exports = /* @__PURE__ */ __exportAll({
	MAX_SAFE_INTEGER: () => MAX_SAFE_INTEGER,
	asc: () => asc,
	getPercentWithPrecision: () => getPercentWithPrecision,
	getPixelPrecision: () => getPixelPrecision,
	getPrecision: () => getPrecision,
	getPrecisionSafe: () => getPrecisionSafe,
	isNumeric: () => isNumeric,
	isRadianAroundZero: () => isRadianAroundZero,
	linearMap: () => linearMap,
	nice: () => nice,
	numericToNumber: () => numericToNumber,
	parseDate: () => parseDate,
	parsePercent: () => parsePercent,
	quantile: () => quantile,
	quantity: () => quantity,
	quantityExponent: () => quantityExponent,
	reformIntervals: () => reformIntervals,
	remRadian: () => remRadian,
	round: () => roundLegacy
});
//#endregion
//#region node_modules/echarts/lib/export/api/time.js
var time_exports = /* @__PURE__ */ __exportAll({
	format: () => format,
	parse: () => parseDate,
	roundTime: () => roundTime
});
//#endregion
//#region node_modules/echarts/lib/export/api/graphic.js
var graphic_exports = /* @__PURE__ */ __exportAll({
	Arc: () => Arc,
	BezierCurve: () => BezierCurve,
	BoundingRect: () => BoundingRect,
	Circle: () => Circle,
	CompoundPath: () => CompoundPath,
	Ellipse: () => Ellipse,
	Group: () => Group,
	Image: () => ZRImage,
	IncrementalDisplayable: () => IncrementalDisplayable,
	Line: () => Line,
	LinearGradient: () => LinearGradient,
	Polygon: () => Polygon,
	Polyline: () => Polyline,
	RadialGradient: () => RadialGradient,
	Rect: () => Rect,
	Ring: () => Ring,
	Sector: () => Sector,
	Text: () => ZRText,
	clipPointsByRect: () => clipPointsByRect,
	clipRectByRect: () => clipRectByRect,
	createIcon: () => createIcon,
	extendPath: () => extendPath,
	extendShape: () => extendShape,
	getShapeClass: () => getShapeClass,
	getTransform: () => getTransform,
	initProps: () => initProps,
	makeImage: () => makeImage,
	makePath: () => makePath,
	mergePath: () => mergePath,
	registerShape: () => registerShape,
	resizePath: () => resizePath,
	updateProps: () => updateProps
});
//#endregion
//#region node_modules/echarts/lib/export/api/format.js
var format_exports = /* @__PURE__ */ __exportAll({
	addCommas: () => addCommas,
	capitalFirst: () => capitalFirst,
	encodeHTML: () => encodeHTML,
	formatTime: () => formatTime,
	formatTpl: () => formatTpl,
	getTextRect: () => getTextRect,
	getTooltipMarker: () => getTooltipMarker,
	normalizeCssArray: () => normalizeCssArray,
	toCamelCase: () => toCamelCase,
	truncateText: () => truncateText
});
//#endregion
//#region node_modules/echarts/lib/export/api/util.js
var util_exports = /* @__PURE__ */ __exportAll({
	bind: () => bind,
	clone: () => clone,
	curry: () => curry,
	defaults: () => defaults,
	each: () => each,
	extend: () => extend,
	filter: () => filter,
	indexOf: () => indexOf,
	inherits: () => inherits,
	isArray: () => isArray,
	isFunction: () => isFunction,
	isObject: () => isObject,
	isString: () => isString,
	map: () => map,
	merge: () => merge,
	reduce: () => reduce
});
//#endregion
//#region node_modules/echarts/lib/export/api.js
/**
* AUTO-GENERATED FILE. DO NOT MODIFY.
*/
function extendComponentModel(proto) {
	var Model = ComponentModel.extend(proto);
	ComponentModel.registerClass(Model);
	return Model;
}
function extendComponentView(proto) {
	var View = ComponentView.extend(proto);
	ComponentView.registerClass(View);
	return View;
}
function extendSeriesModel(proto) {
	var Model = SeriesModel.extend(proto);
	SeriesModel.registerClass(Model);
	return Model;
}
function extendChartView(proto) {
	var View = ChartView.extend(proto);
	ChartView.registerClass(View);
	return View;
}
//#endregion
export { Axis, ChartView, ComponentModel, ComponentView, SeriesData as List, Model, PRIORITY, SeriesModel, color_exports as color, connect, dataTool, dependencies, disConnect, disconnect, dispose, env, extendChartView, extendComponentModel, extendComponentView, extendSeriesModel, format_exports as format, getCoordinateSystemDimensions, getInstanceByDom, getInstanceById, getMap, graphic_exports as graphic, helper_exports as helper, init, brushSingle as innerDrawElementOnCanvas, matrix_exports as matrix, number_exports as number, parseGeoJSON, parseGeoJSON as parseGeoJson, registerAction, registerCoordinateSystem, registerCustomSeries, registerLayout, registerLoading, registerLocale, registerMap, registerPostInit, registerPostUpdate, registerPreprocessor, registerProcessor, registerTheme, registerTransform, registerUpdateLifecycle, registerVisual, setCanvasCreator, setPlatformAPI, throttle, time_exports as time, use, util_exports as util, vector_exports as vector, version, util_exports$1 as zrUtil, zrender_exports as zrender };
