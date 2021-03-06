#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Execut Context Module."""

import math
from typing import Any, Dict, Optional, TYPE_CHECKING

from pyppeteer import helper
from pyppeteer.connection import Session
from pyppeteer.errors import ElementHandleError

if TYPE_CHECKING:
    from pyppeteer.element_handle import ElementHandle  # noqa: F401


class ExecutionContext(object):
    """Execution Context class."""

    def __init__(self, client: Session, contextId: int,
                 objectHandleFactory: Any) -> None:
        self._client = client
        self._contextId = contextId
        self._objectHandleFactory = objectHandleFactory

    async def evaluate(self, pageFunction: str, *args: Any) -> Any:
        """Execute `pageFunction` on this context."""
        handle = await self.evaluateHandle(pageFunction, *args)
        result = await handle.jsonValue()
        await handle.dispose()
        return result

    async def evaluateHandle(self, pageFunction: str, *args: Any
                             ) -> 'JSHandle':
        """Execute `pageFunction` on this context."""
        # if not args:
        #     _obj = await self._client.send('Runtime.evaluate', {
        #         'expression': pageFunction,
        #         'contextId': self._contextId,
        #         'returnByValue': False,
        #         'awaitPromiss': True,
        #     })
        #     exceptionDetails = _obj.get('exceptionDetails')
        #     if exceptionDetails:
        #         raise ElementHandleError(
        #             'Evaluation failed: {}'.format(
        #                 helper.getExceptionMessage(exceptionDetails)))
        #     print(_obj, flush=True)
        #     remoteObject = _obj.get('result')
        #     print(remoteObject, flush=True)
        #     return self._objectHandleFactory(remoteObject)

        _obj = await self._client.send('Runtime.callFunctionOn', {
            'functionDeclaration': pageFunction,
            'executionContextId': self._contextId,
            'arguments': [self._convertArgument(arg) for arg in args],
            'returnByValue': False,
            'awaitPromiss': True,
        })
        exceptionDetails = _obj.get('exceptionDetails')
        if exceptionDetails:
            raise ElementHandleError('Evaluation failed: {}'.format(
                helper.getExceptionMessage(exceptionDetails)))
        remoteObject = _obj.get('result')
        return self._objectHandleFactory(remoteObject)

    def _convertArgument(self, arg: Any) -> Dict:  # noqa: C901
        if arg == math.inf:
            return {'unserializableValue': 'Infinity'}
        if arg == -math.inf:
            return {'unserializableValue': '-Infinity'}
        objectHandle = arg if isinstance(arg, JSHandle) else None
        if objectHandle:
            if objectHandle._context != self:
                raise ElementHandleError('JSHandles can be evaluated only in the context they were created!')  # noqa: E501
            if objectHandle._disposed:
                raise ElementHandleError('JSHandle is disposed!')
            if objectHandle._remoteObject.get('unserializableValue'):
                return {'unserializableValue': objectHandle._remoteObject.get('unserializableValue')}  # noqa: E501
            if not objectHandle._remoteObject.get('objectId'):
                return {'value': objectHandle._remoteObject.get('value')}
            return {'objectId': objectHandle._remoteObject.get('objectId')}
        return {'value': arg}

    async def queryObject(self, prototypeHandle: 'JSHandle') -> 'JSHandle':
        """Send query to the object."""
        if prototypeHandle._disposed:
            raise ElementHandleError('Prototype JSHandle is disposed!')
        if not prototypeHandle._remoteObject.get('objectId'):
            raise ElementHandleError(
                'Prototype JSHandle must not be referencing primitive value')
        response = await self._client.send('Runtime.queryObject', {
            'prototypeObjectId': prototypeHandle._remoteObject['objectId'],
        })
        return self._objectHandleFactory(response.get('objects'))


class JSHandle(object):
    """JS Handle class."""

    def __init__(self, context: ExecutionContext, client: Session,
                 remoteObject: Dict) -> None:
        self._context = context
        self._client = client
        self._remoteObject = remoteObject
        self._disposed = False

    @property
    def executionContext(self) -> ExecutionContext:
        """Get execution context of this handle."""
        return self._context

    async def getProperty(self, propertyName: str) -> 'JSHandle':
        """Get property value of `propertyName`."""
        objectHandle = await self._context.evaluateHandle(
            '''(object, propertyName) => {
                const result = {__proto__: null};
                result[propertyName] = object[propertyName];
                return result;
            }''', self, propertyName)
        properties = await objectHandle.getProperties()
        result = properties[propertyName]
        await objectHandle.dispose()
        return result

    async def getProperties(self) -> Dict[str, 'JSHandle']:
        """Get all properties."""
        response = await self._client.send('Runtime.getProperties', {
            'objectId': self._remoteObject.get('objectId', ''),
            'ownProperties': True
        })
        result = dict()
        for prop in response['result']:
            if not prop.get('enumerable'):
                continue
            result[prop.get('name')] = self._context._objectHandleFactory(
                prop.get('value'))
        return result

    async def jsonValue(self) -> Dict:
        """Get Jsonized value."""
        objectId = self._remoteObject.get('objectId')
        if objectId:
            response = await self._client.send('Runtime.callFunctionOn', {
                'functionDeclaration': 'function() { return this; }',
                'objectId': objectId,
                'returnByValue': True,
                'awaitPromiss': True,
            })
            return helper.valueFromRemoteObject(response['result'])
        return helper.valueFromRemoteObject(self._remoteObject)

    def asElement(self) -> Optional['ElementHandle']:
        """Get as element."""
        return None

    async def dispose(self) -> None:
        """Dispose this handle."""
        if self._disposed:
            return
        self._disposed = True
        await helper.releaseObject(self._client, self._remoteObject)

    def toString(self) -> str:
        """Get string representation."""
        if self._remoteObject.get('objectId'):
            _type = (self._remoteObject.get('subtype') or
                     self._remoteObject.get('type'))
            return f'JSHandle@{_type}'
        return 'JSHandle: {}'.format(
            helper.valueFromRemoteObject(self._remoteObject))
