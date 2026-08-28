<?xml version="1.0" encoding="UTF-8"?>
<xsl:stylesheet xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
    version="1.0">

    <xsl:template name="hex2num">
        <xsl:param name="hex"/>
        <xsl:param name="num" select="(number(0))"/>
        <xsl:param name="MSB" select="translate(substring($hex, 1, 1), 'abcdef', 'ABCDEF')"/>
        <xsl:param name="value" select="string-length(substring-before('0123456789ABCDEF', $MSB))"/>
        <xsl:param name="result" select="(number(16 * $num + $value))"/>
        <xsl:choose>
            <xsl:when test="string-length($hex) > 1">
                <xsl:call-template name="hex2num">
                    <xsl:with-param name="hex" select="substring($hex, 2)"/>
                    <xsl:with-param name="num" select="$result"/>
                </xsl:call-template>
            </xsl:when>
            <xsl:otherwise>
                <xsl:value-of select="$result"/>
            </xsl:otherwise>
        </xsl:choose>
    </xsl:template>

    <xsl:template name="decimalToHex">
        <xsl:param name="dec"/>
        <xsl:if test="$dec > 0">
            <xsl:call-template name="decimalToHex">
                <xsl:with-param name="dec" select="floor($dec div 16)"/>
            </xsl:call-template>
            <xsl:value-of select="substring('0123456789ABCDEF', (($dec mod 16) + 1), 1)"/>
        </xsl:if>
    </xsl:template>

</xsl:stylesheet>
