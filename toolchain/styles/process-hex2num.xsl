<?xml version="1.0" encoding="UTF-8"?>
<xsl:stylesheet xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
    version="1.0">

    <xsl:import href="hex2num_template.xsl"/>

    <!-- Create a new XML file with the name derived from the description -->
    <xsl:variable name="description" select="/device/peripherals/peripheral/name/text()"/>
    <xsl:variable name="outputFileName" select="concat($description, '-abs.xml')"/>

    <!-- Identity template to copy everything by default -->
    <xsl:template match="@*|node()">
        <xsl:copy>
            <xsl:apply-templates select="@*|node()"/>
        </xsl:copy>
    </xsl:template>

    <!-- Template to process each register and add the address field after resetValue and before fields -->
    <xsl:template match="register">
        <xsl:variable name="baseAddress" select="../../baseAddress/text()"/>
        <xsl:variable name="offset" select="addressOffset/text()"/>

        <!-- Capture the result of hex2num for baseAddress -->
        <xsl:variable name="baseNum">
            <xsl:call-template name="hex2num">
                <xsl:with-param name="hex" select="$baseAddress"/>
            </xsl:call-template>
        </xsl:variable>

        <!-- Capture the result of hex2num for offset -->
        <xsl:variable name="offsetNum">
            <xsl:call-template name="hex2num">
                <xsl:with-param name="hex" select="$offset"/>
            </xsl:call-template>
        </xsl:variable>

        <!-- Calculate the absolute address in decimal -->
        <xsl:variable name="absoluteAddressDecimal" select="$baseNum + $offsetNum"/>

        <!-- Convert the absolute address to hexadecimal -->
        <xsl:variable name="absoluteAddressHex">
            <xsl:call-template name="decimalToHex">
                <xsl:with-param name="dec" select="$absoluteAddressDecimal"/>
            </xsl:call-template>
        </xsl:variable>

        <!-- Output the register with the new address field after resetValue and before fields -->
        <xsl:element name="{name()}">
            <xsl:apply-templates select="@*|node()[not(self::resetValue) and not(self::fields)]"/>
            <xsl:if test="resetValue">
                <xsl:copy-of select="resetValue"/>
                <!-- Add newline after resetValue -->
                <xsl:text>&#10;</xsl:text>
                <address><xsl:value-of select="concat('$', $absoluteAddressHex)"/></address>
                <!-- Add newline after address -->
                <xsl:text>&#10;</xsl:text>
            </xsl:if>
            <xsl:apply-templates select="fields"/>
        </xsl:element>
    </xsl:template>

</xsl:stylesheet>
