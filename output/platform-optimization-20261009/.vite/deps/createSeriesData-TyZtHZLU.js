import { Gn as prepareSeriesDataSchema, Hi as SINGLE_REFERRING, Ii as SOURCE_FORMAT_ORIGINAL, In as enableDataStack, Kn as SeriesData, Xi as getDataItemValue, er as getDimensionTypeByAxis, nr as createSourceFromSeriesDataOption, rr as makeSeriesEncodeForAxisCoordSys, zn as CoordinateSystemManager } from "./parseGeoJson-BuroNMpY.js";
import { $n as map, Dn as createHashMap, Hn as isFunction, On as curry, jn as each, or as retrieve, zn as isArray } from "./graphic-CKloBv3l.js";
//#region node_modules/echarts/lib/model/referHelper.js
/**
* AUTO-GENERATED FILE. DO NOT MODIFY.
*/
/**
* Helper for model references.
* There are many manners to refer axis/coordSys.
*/
/**
* @class
* For example:
* {
*     coordSysName: 'cartesian2d',
*     coordSysDims: ['x', 'y', ...],
*     axisMap: HashMap({
*         x: xAxisModel,
*         y: yAxisModel
*     }),
*     categoryAxisMap: HashMap({
*         x: xAxisModel,
*         y: undefined
*     }),
*     // The index of the first category axis in `coordSysDims`.
*     // `null/undefined` means no category axis exists.
*     firstCategoryDimIndex: 1,
*     // To replace user specified encode.
* }
*/
var SeriesModelCoordSysInfo = function() {
	function SeriesModelCoordSysInfo(coordSysName) {
		this.coordSysDims = [];
		this.axisMap = createHashMap();
		this.categoryAxisMap = createHashMap();
		this.coordSysName = coordSysName;
	}
	return SeriesModelCoordSysInfo;
}();
function getCoordSysInfoBySeries(seriesModel) {
	var coordSysName = seriesModel.get("coordinateSystem");
	var result = new SeriesModelCoordSysInfo(coordSysName);
	var fetch = fetchers[coordSysName];
	if (fetch) {
		fetch(seriesModel, result, result.axisMap, result.categoryAxisMap);
		return result;
	}
}
var fetchers = {
	cartesian2d: function(seriesModel, result, axisMap, categoryAxisMap) {
		var xAxisModel = seriesModel.getReferringComponents("xAxis", SINGLE_REFERRING).models[0];
		var yAxisModel = seriesModel.getReferringComponents("yAxis", SINGLE_REFERRING).models[0];
		if (!xAxisModel) throw new Error("xAxis \"" + retrieve(seriesModel.get("xAxisIndex"), seriesModel.get("xAxisId"), 0) + "\" not found");
		if (!yAxisModel) throw new Error("yAxis \"" + retrieve(seriesModel.get("xAxisIndex"), seriesModel.get("yAxisId"), 0) + "\" not found");
		result.coordSysDims = ["x", "y"];
		axisMap.set("x", xAxisModel);
		axisMap.set("y", yAxisModel);
		if (isCategory(xAxisModel)) {
			categoryAxisMap.set("x", xAxisModel);
			result.firstCategoryDimIndex = 0;
		}
		if (isCategory(yAxisModel)) {
			categoryAxisMap.set("y", yAxisModel);
			result.firstCategoryDimIndex ??= 1;
		}
	},
	singleAxis: function(seriesModel, result, axisMap, categoryAxisMap) {
		var singleAxisModel = seriesModel.getReferringComponents("singleAxis", SINGLE_REFERRING).models[0];
		if (!singleAxisModel) throw new Error("singleAxis should be specified.");
		result.coordSysDims = ["single"];
		axisMap.set("single", singleAxisModel);
		if (isCategory(singleAxisModel)) {
			categoryAxisMap.set("single", singleAxisModel);
			result.firstCategoryDimIndex = 0;
		}
	},
	polar: function(seriesModel, result, axisMap, categoryAxisMap) {
		var polarModel = seriesModel.getReferringComponents("polar", SINGLE_REFERRING).models[0];
		var radiusAxisModel = polarModel.findAxisModel("radiusAxis");
		var angleAxisModel = polarModel.findAxisModel("angleAxis");
		if (!angleAxisModel) throw new Error("angleAxis option not found");
		if (!radiusAxisModel) throw new Error("radiusAxis option not found");
		result.coordSysDims = ["radius", "angle"];
		axisMap.set("radius", radiusAxisModel);
		axisMap.set("angle", angleAxisModel);
		if (isCategory(radiusAxisModel)) {
			categoryAxisMap.set("radius", radiusAxisModel);
			result.firstCategoryDimIndex = 0;
		}
		if (isCategory(angleAxisModel)) {
			categoryAxisMap.set("angle", angleAxisModel);
			result.firstCategoryDimIndex ??= 1;
		}
	},
	geo: function(seriesModel, result, axisMap, categoryAxisMap) {
		result.coordSysDims = ["lng", "lat"];
	},
	parallel: function(seriesModel, result, axisMap, categoryAxisMap) {
		var ecModel = seriesModel.ecModel;
		var parallelModel = ecModel.getComponent("parallel", seriesModel.get("parallelIndex"));
		var coordSysDims = result.coordSysDims = parallelModel.dimensions.slice();
		each(parallelModel.parallelAxisIndex, function(axisIndex, index) {
			var axisModel = ecModel.getComponent("parallelAxis", axisIndex);
			var axisDim = coordSysDims[index];
			axisMap.set(axisDim, axisModel);
			if (isCategory(axisModel)) {
				categoryAxisMap.set(axisDim, axisModel);
				if (result.firstCategoryDimIndex == null) result.firstCategoryDimIndex = index;
			}
		});
	},
	matrix: function(seriesModel, result, axisMap, categoryAxisMap) {
		var matrixModel = seriesModel.getReferringComponents("matrix", SINGLE_REFERRING).models[0];
		if (!matrixModel) throw new Error("matrix coordinate system should be specified.");
		result.coordSysDims = ["x", "y"];
		var xModel = matrixModel.getDimensionModel("x");
		var yModel = matrixModel.getDimensionModel("y");
		axisMap.set("x", xModel);
		axisMap.set("y", yModel);
		categoryAxisMap.set("x", xModel);
		categoryAxisMap.set("y", yModel);
	}
};
function isCategory(axisModel) {
	return axisModel.get("type") === "category";
}
//#endregion
//#region node_modules/echarts/lib/chart/helper/createSeriesData.js
/**
* AUTO-GENERATED FILE. DO NOT MODIFY.
*/
function getCoordSysDimDefs(seriesModel, coordSysInfo) {
	var coordSysName = seriesModel.get("coordinateSystem");
	var registeredCoordSys = CoordinateSystemManager.get(coordSysName);
	var coordSysDimDefs;
	if (coordSysInfo && coordSysInfo.coordSysDims) coordSysDimDefs = map(coordSysInfo.coordSysDims, function(dim) {
		var dimInfo = { name: dim };
		var axisModel = coordSysInfo.axisMap.get(dim);
		if (axisModel) dimInfo.type = getDimensionTypeByAxis(axisModel.get("type"));
		return dimInfo;
	});
	if (!coordSysDimDefs) coordSysDimDefs = registeredCoordSys && (registeredCoordSys.getDimensionsInfo ? registeredCoordSys.getDimensionsInfo() : registeredCoordSys.dimensions.slice()) || ["x", "y"];
	return coordSysDimDefs;
}
function injectOrdinalMeta(dimInfoList, createInvertedIndices, coordSysInfo) {
	var firstCategoryDimIndex;
	var hasNameEncode;
	coordSysInfo && each(dimInfoList, function(dimInfo, dimIndex) {
		var coordDim = dimInfo.coordDim;
		var categoryAxisModel = coordSysInfo.categoryAxisMap.get(coordDim);
		if (categoryAxisModel) {
			if (firstCategoryDimIndex == null) firstCategoryDimIndex = dimIndex;
			dimInfo.ordinalMeta = categoryAxisModel.getOrdinalMeta();
			if (createInvertedIndices) dimInfo.createInvertedIndices = true;
		}
		if (dimInfo.otherDims.itemName != null) hasNameEncode = true;
	});
	if (!hasNameEncode && firstCategoryDimIndex != null) dimInfoList[firstCategoryDimIndex].otherDims.itemName = 0;
	return firstCategoryDimIndex;
}
/**
* Caution: there are side effects to `sourceManager` in this method.
* Should better only be called in `Series['getInitialData']`.
*/
function createSeriesData(sourceRaw, seriesModel, opt) {
	opt = opt || {};
	var sourceManager = seriesModel.getSourceManager();
	var source;
	var isOriginalSource = false;
	if (sourceRaw) {
		isOriginalSource = true;
		source = createSourceFromSeriesDataOption(sourceRaw);
	} else {
		source = sourceManager.getSource();
		isOriginalSource = source.sourceFormat === SOURCE_FORMAT_ORIGINAL;
	}
	var coordSysInfo = getCoordSysInfoBySeries(seriesModel);
	var coordSysDimDefs = getCoordSysDimDefs(seriesModel, coordSysInfo);
	var useEncodeDefaulter = opt.useEncodeDefaulter;
	var encodeDefaulter = isFunction(useEncodeDefaulter) ? useEncodeDefaulter : useEncodeDefaulter ? curry(makeSeriesEncodeForAxisCoordSys, coordSysDimDefs, seriesModel) : null;
	var createDimensionOptions = {
		coordDimensions: coordSysDimDefs,
		generateCoord: opt.generateCoord,
		encodeDefine: seriesModel.getEncode(),
		encodeDefaulter,
		canOmitUnusedDimensions: !isOriginalSource
	};
	var schema = prepareSeriesDataSchema(source, createDimensionOptions);
	var firstCategoryDimIndex = injectOrdinalMeta(schema.dimensions, opt.createInvertedIndices, coordSysInfo);
	var store = !isOriginalSource ? sourceManager.getSharedDataStore(schema) : null;
	var stackCalculationInfo = enableDataStack(seriesModel, {
		schema,
		store
	});
	var data = new SeriesData(schema, seriesModel);
	data.setCalculationInfo(stackCalculationInfo);
	var dimValueGetter = firstCategoryDimIndex != null && isNeedCompleteOrdinalData(source) ? function(itemOpt, dimName, dataIndex, dimIndex) {
		return dimIndex === firstCategoryDimIndex ? dataIndex : this.defaultDimValueGetter(itemOpt, dimName, dataIndex, dimIndex);
	} : null;
	data.hasItemOption = false;
	data.initData(isOriginalSource ? source : store, null, dimValueGetter);
	return data;
}
function isNeedCompleteOrdinalData(source) {
	if (source.sourceFormat === "original") return !isArray(getDataItemValue(firstDataNotNull(source.data || [])));
}
function firstDataNotNull(arr) {
	var i = 0;
	while (i < arr.length && arr[i] == null) i++;
	return arr[i];
}
//#endregion
export { createSeriesData as t };
