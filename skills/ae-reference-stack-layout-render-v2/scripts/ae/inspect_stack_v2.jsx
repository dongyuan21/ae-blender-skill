/* v2: read-only board/tile inspection with route-scoped issue baselines. */
(function () {
    app.exitAfterLaunchAndEval = true;

    function readText(path) {
        var file = new File(path); file.encoding = "UTF-8";
        if (!file.open("r")) throw new Error("Cannot read: " + path);
        var value = file.read(); file.close(); return value;
    }
    function quote(value) { return '"' + String(value).replace(/\\/g,"\\\\").replace(/"/g,'\\"').replace(/\r/g,"\\r").replace(/\n/g,"\\n").replace(/\t/g,"\\t") + '"'; }
    function json(value) {
        if (value === null || value === undefined) return "null";
        if (typeof value === "string") return quote(value);
        if (typeof value === "number") return isFinite(value) ? String(value) : "null";
        if (typeof value === "boolean") return value ? "true" : "false";
        if (value instanceof Array) { var rows=[],i; for(i=0;i<value.length;i++) rows.push(json(value[i])); return "["+rows.join(",")+"]"; }
        var pairs=[],key; for(key in value) if(value.hasOwnProperty(key)) pairs.push(quote(key)+":"+json(value[key])); return "{"+pairs.join(",")+"}";
    }
    function writeJson(path,value) { var file=new File(path); file.encoding="UTF-8"; if(!file.open("w"))throw new Error("Cannot write: "+path); file.write(json(value)); file.close(); }
    function normalize(path) { return String(path).replace(/\\/g,"/").toLowerCase(); }
    function findItemById(id) { var i,item; for(i=1;i<=app.project.numItems;i++){item=app.project.item(i);if(item&&Number(item.id)===Number(id))return item;}return null; }
    function cloneValue(value) { if(value instanceof Array){var rows=[],i;for(i=0;i<value.length;i++)rows.push(Number(value[i]));return rows;}return Number(value); }
    function propertySnapshot(property) {
        if(!property)return null;
        var result={name:String(property.name),matchName:String(property.matchName),numKeys:Number(property.numKeys),expressionEnabled:false,expression:null,value:null,keys:[]},i;
        try{result.value=cloneValue(property.value);}catch(ignoreValue){}
        try{result.expressionEnabled=!!property.expressionEnabled;if(property.expressionEnabled)result.expression=String(property.expression);}catch(ignoreExpression){}
        for(i=1;i<=property.numKeys;i++){
            result.keys.push({keyNumber:i,time:Number(property.keyTime(i)),value:cloneValue(property.keyValue(i))});
        }
        return result;
    }
    function layerSnapshot(comp,layer) {
        var sourceId=null,sourceName=null,sourceType=null,sourceWidth=null,sourceHeight=null,parentIndex=null;
        try{
            if(layer.source){
                sourceId=Number(layer.source.id);sourceName=String(layer.source.name);
                sourceWidth=Number(layer.source.width);sourceHeight=Number(layer.source.height);
                sourceType=(layer.source instanceof CompItem)?"comp":((layer.source instanceof FootageItem)?"footage":"avitem");
            }
        }catch(ignoreSource){}
        try{if(layer.parent)parentIndex=Number(layer.parent.index);}catch(ignoreParent){}
        var transform=layer.property("ADBE Transform Group"),position=null,scale=null,opacity=null,anchor=null,rotation=null;
        if(transform){
            position=propertySnapshot(transform.property("ADBE Position"));
            scale=propertySnapshot(transform.property("ADBE Scale"));
            opacity=propertySnapshot(transform.property("ADBE Opacity"));
            anchor=propertySnapshot(transform.property("ADBE Anchor Point"));
            rotation=propertySnapshot(transform.property("ADBE Rotate Z"));
        }
        return {
            compId:Number(comp.id),index:Number(layer.index),name:String(layer.name),enabled:!!layer.enabled,
            inPoint:Number(layer.inPoint),outPoint:Number(layer.outPoint),startTime:Number(layer.startTime),
            sourceId:sourceId,sourceName:sourceName,sourceType:sourceType,sourceWidth:sourceWidth,sourceHeight:sourceHeight,
            parentIndex:parentIndex,hasTrackMatte:!!layer.hasTrackMatte,threeDLayer:!!layer.threeDLayer,
            transform:{anchor:anchor,position:position,scale:scale,rotation:rotation,opacity:opacity}
        };
    }
    function containsNumber(values,target){var i;if(!(values instanceof Array))return false;for(i=0;i<values.length;i++)if(Number(values[i])===Number(target))return true;return false;}
    function routeAllowsComp(scope,compId){return !scope||containsNumber(scope.compIds,compId);}
    function routeAllowsFootage(scope,itemId){return !scope||containsNumber(scope.routeCriticalFootageItemIds,itemId);}
    function missingKey(row){return String(row.itemId)+"|"+normalize(row.path||"");}
    function expressionKey(row){return String(row.path||"")+"|"+String(row.error||"");}
    function watermarkKey(row){return String(row.compId)+"/"+String(row.layerIndex)+"|"+String(row.layerName||"")+"|"+String(row.sourceName||"");}
    function keys(rows,keyFunction){var result=[],i;for(i=0;i<rows.length;i++)result.push(keyFunction(rows[i]));return result;}
    function missingFootage(scope) {
        var rows=[],i,item,file;
        for(i=1;i<=app.project.numItems;i++){
            item=app.project.item(i);if(!item||!(item instanceof FootageItem)||!routeAllowsFootage(scope,Number(item.id)))continue;
            file=null;try{file=item.file;}catch(ignoreFile){}
            if(file&&!file.exists)rows.push({itemId:Number(item.id),itemName:String(item.name),path:String(file.fsName)});
        }
        return rows;
    }
    function scanGroup(group,path,errors){
        if(!group||!group.numProperties)return;var i,p;
        for(i=1;i<=group.numProperties;i++){
            p=group.property(i);if(!p)continue;
            if(p.propertyType===PropertyType.PROPERTY){try{if(p.expressionEnabled&&p.expressionError)errors.push({path:path+"/"+p.name,error:String(p.expressionError)});}catch(ignoreExpression){}}
            else scanGroup(p,path+"/"+p.name,errors);
        }
    }
    function expressionErrors(scope) {
        var rows=[],i,item,j;
        for(i=1;i<=app.project.numItems;i++){
            item=app.project.item(i);if(!item||!(item instanceof CompItem)||!routeAllowsComp(scope,Number(item.id)))continue;
            for(j=1;j<=item.numLayers;j++)scanGroup(item.layer(j),String(item.name)+"/"+String(item.layer(j).name),rows);
        }
        return rows;
    }
    function watermarkLayers(pattern,scope) {
        var rows=[],i,item,j,layer,sourceName,haystack;
        for(i=1;i<=app.project.numItems;i++){
            item=app.project.item(i);if(!item||!(item instanceof CompItem)||!routeAllowsComp(scope,Number(item.id)))continue;
            for(j=1;j<=item.numLayers;j++){
                layer=item.layer(j);sourceName="";try{if(layer.source)sourceName=String(layer.source.name);}catch(ignoreSource){}
                haystack=String(layer.name)+" "+sourceName;
                if(pattern.test(haystack))rows.push({compId:Number(item.id),compName:String(item.name),layerIndex:Number(layer.index),layerName:String(layer.name),sourceName:sourceName,enabled:!!layer.enabled});
            }
        }
        return rows;
    }

    var resultPath=null;
    try{
        var jobPath=$.getenv("AE_STACK_V2_JOB");if(!jobPath)throw new Error("AE_STACK_V2_JOB is not set");
        var job=eval("("+readText(jobPath)+")");resultPath=job.resultPath;
        var projectPath=normalize(File(job.projectPath).fsName),staging=normalize(Folder(job.libraryPath).fsName)+"/.staging/";
        if(projectPath.indexOf(staging)!==0)throw new Error("Inspection project is outside library staging");
        app.open(new File(job.projectPath));
        var comp=findItemById(Number(job.compId));if(!comp||!(comp instanceof CompItem))throw new Error("Board comp not found: "+job.compId);
        var tilePattern=new RegExp(job.tileLayerNamePattern||"^tile[0-9]+$","i");
        var moverPattern=new RegExp(job.moverLayerNamePattern||"movetop|move|fly","i");
        var handPattern=new RegExp(job.handLayerNamePattern||"hand|finger","i");
        var watermarkPattern=new RegExp(job.watermarkPattern||"watermark|水印","i");
        var tiles=[],movers=[],hands=[],others=[],allLayers=[],i,layer,snapshot,positionKeys,scaleKeys;
        for(i=1;i<=comp.numLayers;i++){
            layer=comp.layer(i);snapshot=layerSnapshot(comp,layer);
            if(job.includeAllLayers!==false)allLayers.push(snapshot);
            if(handPattern.test(String(layer.name))){hands.push(snapshot);continue;}
            if(moverPattern.test(String(layer.name))){movers.push(snapshot);continue;}
            if(tilePattern.test(String(layer.name))){tiles.push(snapshot);continue;}
            positionKeys=snapshot.transform.position?snapshot.transform.position.numKeys:0;
            scaleKeys=snapshot.transform.scale?snapshot.transform.scale.numKeys:0;
            if(positionKeys>0||scaleKeys>0)others.push(snapshot);
        }
        var pairCandidates=[],t,m,frameTolerance=2/Number(comp.frameRate);
        for(t=0;t<tiles.length;t++){
            if(tiles[t].sourceId===null||tiles[t].outPoint>=Number(comp.duration)-frameTolerance)continue;
            for(m=0;m<movers.length;m++){
                if(movers[m].sourceId!==tiles[t].sourceId)continue;
                if(Math.abs(Number(movers[m].inPoint)-Number(tiles[t].outPoint))<=frameTolerance){
                    pairCandidates.push({staticLayerIndex:tiles[t].index,moverLayerIndex:movers[m].index,sourceId:tiles[t].sourceId,staticOutPoint:tiles[t].outPoint,moverInPoint:movers[m].inPoint,timeDelta:Number(movers[m].inPoint)-Number(tiles[t].outPoint)});
                }
            }
        }
        var scope=null;if(job.routeCompIds instanceof Array||job.routeCriticalFootageItemIds instanceof Array)scope={compIds:(job.routeCompIds instanceof Array)?job.routeCompIds:[],routeCriticalFootageItemIds:(job.routeCriticalFootageItemIds instanceof Array)?job.routeCriticalFootageItemIds:[]};var missing=missingFootage(scope),expressions=expressionErrors(scope),watermarks=watermarkLayers(watermarkPattern,scope);
        var result={
            ok:true,mode:"read-only-stack-inspection-v2",projectPath:File(job.projectPath).fsName,
            comp:{id:Number(comp.id),name:String(comp.name),width:Number(comp.width),height:Number(comp.height),duration:Number(comp.duration),frameRate:Number(comp.frameRate),layerCount:Number(comp.numLayers)},
            routeScope:scope,
            patterns:{tile:String(tilePattern),mover:String(moverPattern),hand:String(handPattern),watermark:String(watermarkPattern)},
            tileLayers:tiles,moverLayers:movers,handLayers:hands,otherAnimatedLayers:others,allLayers:allLayers,
            pairCandidates:pairCandidates,missingFootage:missing,expressionErrors:expressions,watermarkLayers:watermarks,
            baselineIssueKeys:{acceptedMissingKeys:keys(missing,missingKey),acceptedMissingFootageKeys:keys(missing,missingKey),acceptedExpressionErrorKeys:keys(expressions,expressionKey),acceptedEnabledWatermarkKeys:keys((function(){var a=[],k;for(k=0;k<watermarks.length;k++)if(watermarks[k].enabled)a.push(watermarks[k]);return a;}()),watermarkKey)},
            referenceSourceAepUsed:false,referenceSourceGeometryUsed:false
        };
        writeJson(resultPath,result);
        try{app.project.close(CloseOptions.DO_NOT_SAVE_CHANGES);}catch(ignoreClose){}try{app.quit();}catch(ignoreQuit){}
    }catch(error){if(resultPath){try{writeJson(resultPath,{ok:false,error:String(error),line:error.line||null});}catch(ignoreWrite){}}try{app.quit();}catch(ignoreQuitOnError){}}
}());
