package util

import (
	"net/http"

	nef_context "github.com/free5gc/nef/internal/context"
	"github.com/free5gc/nef/internal/logger"
	"github.com/free5gc/openapi/models"
	"github.com/gin-gonic/gin"
)

// Metrics consts
const (
	METRICS_APP_PFDS_CREATION_ERR_MSG = "PFDs for all application were not created successfully"
)

type RouterAuthorizationCheck struct {
	serviceName models.ServiceName
}

func NewRouterAuthorizationCheck(serviceName models.ServiceName) *RouterAuthorizationCheck {
	return &RouterAuthorizationCheck{
		serviceName: serviceName,
	}
}

func (rac *RouterAuthorizationCheck) Check(c *gin.Context, nefCtx nef_context.NFContext) {
	token := c.Request.Header.Get("Authorization")
	if err := nefCtx.AuthorizationCheck(token, rac.serviceName); err != nil {
		logger.UtilLog.Debugf("RouterAuthorizationCheck::Check Unauthorized: %s", err.Error())
		c.JSON(http.StatusUnauthorized, gin.H{"error": err.Error()})
		c.Abort()
		return
	}
	logger.UtilLog.Debugf("RouterAuthorizationCheck::Check Authorized")
}
